"""Stage 3 smoke test: discover modules under examples/modules/, install
them in dep order, then run the same scenario as before.

Set PYVELM_DSN, e.g. in .env (see .env.example).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from pyvelm import Environment, Registry, loader
from pyvelm.web import create_app

load_dotenv(".env")

HERE = Path(__file__).parent
MODULES_ROOT = HERE / "modules"


def main():
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env)")

    # autocommit=True at the connection level so ad-hoc statements
    # outside `env.transaction()` are auto-committed; the transaction
    # context flips it temporarily for atomic install/migrate.
    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)

        # Tear down anything left over from previous runs so we install
        # from scratch. Real apps would never do this; the example does
        # so each run starts clean.
        _drop_known_tables(conn)

        specs = loader.load_and_install([MODULES_ROOT], env)
        print("Loaded modules:", [s.name for s in specs])

        Partner = env["res.partner"]
        Country = env["res.country"]
        Region = env["res.region"]
        Tag = env["res.tag"]

        europe = Region.create({"name": "Europe"})
        asia_region = Region.create({"name": "Asia"})
        france = Country.create({"name": "France", "code": "FR", "region_id": europe})
        japan = Country.create({"name": "Japan", "code": "JP", "region_id": asia_region})

        alice = Partner.create({"name": "Alice", "age": 30, "country_id": france})
        bob = Partner.create({"name": "Bob", "age": 25, "country_id": japan})
        carol = Partner.create({"name": "Carol", "age": 40, "parent_id": alice})
        print("Created:", alice, bob, carol)

        # Computed fields still work.
        assert alice.display_name == "Alice [FR] (Europe)"
        assert bob.display_name == "Bob [JP] (Asia)"
        assert alice.age_bucket == "mid"

        # Two-hop M2o invalidation across module boundary: changing Europe's
        # name walks back through country_id, region_id to Alice.
        europe.write({"name": "EU"})
        assert alice.display_name == "Alice [FR] (EU)"
        print("after Europe rename:", alice.display_name)

        # Domain traversal still works.
        in_europe = Partner.search([("country_id.region_id.name", "=", "EU")])
        assert alice in in_europe
        assert bob not in in_europe
        print("Partners in Europe:", [p.name for p in in_europe])

        # M2m EXISTS still works.
        vip = Tag.create({"name": "VIP"})
        alice.write({"tag_ids": [vip]})
        vips = Partner.search([("tag_ids.name", "=", "VIP")])
        assert alice in vips
        print("VIP partners:", [p.name for p in vips])

        # Transactions: rollback on exception.
        try:
            with env.transaction():
                bob.write({"name": "Robert"})
                # bob.name is provisionally "Robert" inside the tx...
                assert bob.name == "Robert"
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        # The tx rolled back, but our cache still holds the optimistic value.
        # Drop it to read from SQL.
        env.cache.invalidate(model_name="res.partner", ids=[bob.id], fields=["name"])
        assert bob.name == "Bob", f"expected rollback, got {bob.name!r}"
        print("transaction rollback verified: bob.name =", bob.name)

        # ir_module bookkeeping.
        rows = conn.execute('SELECT name, version FROM ir_module ORDER BY name').fetchall()
        print("ir_module:", rows)

        # ----- Migration demo -----
        # Fresh install of partners=0.2.0 created the `code` column from
        # the model declaration but didn't run the migration (no upgrade
        # gap). Simulate "an existing 0.1.0 install upgrading to 0.2.0":
        #   - downgrade ir_module to 0.1.0
        #   - null out the code column (as if it never existed in 0.1.0)
        #   - re-run install — loader sees the gap, runs the migration
        conn.execute("UPDATE ir_module SET version = '0.1.0' WHERE name = 'partners'")
        conn.execute('UPDATE res_partner SET code = NULL')
        env.cache.invalidate(model_name="res.partner", fields=["code"])

        # Re-install. Models are already loaded; just kick off install.
        loader.install(specs, env)

        rows = conn.execute(
            'SELECT name, version FROM ir_module ORDER BY name'
        ).fetchall()
        print("ir_module after upgrade:", rows)
        assert dict(rows)["partners"] == "0.2.0"

        codes = conn.execute(
            'SELECT name, code FROM res_partner ORDER BY id'
        ).fetchall()
        print("backfilled codes:", codes)
        assert all(c is not None for _, c in codes), codes
        assert codes[0] == ("Alice", "ALI-1")

        # Idempotency: a third install run is a no-op (versions match).
        loader.install(specs, env)
        rows2 = conn.execute(
            'SELECT name, version FROM ir_module ORDER BY name'
        ).fetchall()
        assert rows2 == rows, "idempotent install should not change versions"
        print("third install is a no-op:", rows2 == rows)

    # ----- HTTP layer (Stage 4 Slice A) -----
    # Outside the install connection: stand up a pool, build the FastAPI
    # app against the loaded registry, and exercise the read endpoints
    # via ASGI in-process (no port binding).
    with ConnectionPool(dsn, min_size=1, max_size=2, open=True) as pool:
        app = create_app(reg, pool)
        with TestClient(app) as client:
            # 1. Fetch the resolved view (post-inheritance — partners_pro
            # patched it). Verify it parses and project field names out
            # of the normalized list-of-dicts form.
            resp = client.get("/api/views/partners/partner.list")
            assert resp.status_code == 200, resp.text
            view = resp.json()
            print("GET /api/views/partners/partner.list ->", view)
            assert view["model"] == "res.partner"
            assert view["view_type"] == "list"
            field_names = [f["name"] for f in view["arch"]["fields"]]

            # 2. Use the resolved field list to pull partner data.
            field_csv = ",".join(field_names)
            resp = client.get(
                "/api/records",
                params={"model": "res.partner", "fields": field_csv,
                        "order": '"id" ASC'},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            print("GET /api/records ->", body)
            assert body["count"] == 3
            alice = body["records"][0]
            # Many2one serializes as [id, display_value]
            assert alice["country_id"][1] in {"France", "Alice [FR] (EU)", "France"}
            assert alice["code"] == "ALI-1"

            # 3. Domain filter via the API.
            resp = client.get(
                "/api/records",
                params={
                    "model": "res.partner",
                    "fields": "name,code",
                    "domain": '[["country_id.region_id.name", "=", "EU"]]',
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["count"] == 1
            assert body["records"][0]["name"] == "Alice"
            print("Domain-filtered list:", body["records"])

            # 4. 404 on a missing view; 404 on an unknown model.
            assert client.get("/api/views/partners/nope").status_code == 404
            assert client.get("/api/records", params={"model": "no.such"}).status_code == 404

            # 5. View inheritance: partners_pro patched the base view.
            #   - remove age, insert tag_ids after country_id,
            #   - `update` decorated `active` with widget + readonly,
            #   - `set` added a label to `code`.
            resp = client.get("/api/views/partners/partner.list")
            arch = resp.json()["arch"]
            print("resolved arch (post-inheritance):", arch)
            fields_by_name = {f["name"]: f for f in arch["fields"]}
            assert list(fields_by_name) == [
                "name", "code", "country_id", "tag_ids", "active",
            ]
            # `update` merged two attrs into the existing field dict.
            assert fields_by_name["active"]["widget"] == "toggle"
            assert fields_by_name["active"]["readonly"] is True
            # Granular `set` added a brand-new key on the code field.
            assert fields_by_name["code"]["label"] == "Partner code"

            # Same answer whether you ask through the base or the extension.
            resp2 = client.get("/api/views/partners_pro/partner.list.pro")
            assert resp2.json()["arch"] == arch
            print("inheritance verified from both ends")

            # 6. HTML renderer: full page + HTMX rows fragment.
            resp = client.get(
                "/web/views/partners/partner.list",
                params={"page": 0, "page_size": 2},
            )
            assert resp.status_code == 200, resp.text
            assert resp.headers["content-type"].startswith("text/html")
            html = resp.text
            # Structural assertions — markup specifics aren't exhaustively
            # checked, just the load-bearing pieces.
            assert "cdn.tailwindcss.com" in html      # Tailwind via Play CDN
            assert "htmx.org" in html                  # HTMX script tag
            assert 'id="pyvelm-rows"' in html
            assert "ALI-1" in html                     # Alice's code first page
            # Toggle widget for `active` — green track when value is True.
            assert "bg-green-500" in html
            # Pagination button present because total > page_size.
            assert "Load 2 more" in html
            print("HTML list view renders with Tailwind widgets + pagination")

            # 7. HTMX fragment endpoint returns just <tr>s + OOB load-more.
            resp = client.get(
                "/web/records/partners/partner.list",
                params={"page": 1, "page_size": 2},
            )
            assert resp.status_code == 200, resp.text
            frag = resp.text
            # No <html>/<body> in a fragment response.
            assert "<html" not in frag
            assert "<tr" in frag
            assert "BOB-2" in frag or "CAR-3" in frag

            # Static directory still mounted (used for future per-app
            # assets); the placeholder pyvelm.css is served as-is.
            resp = client.get("/web/static/pyvelm.css")
            assert resp.status_code == 200, resp.text

            # ----- B.3: JSON mutation endpoints -----
            # Create
            resp = client.post(
                "/api/records",
                params={"model": "res.partner"},
                json={"name": "Eve", "age": 22, "country_id": france.id},
            )
            assert resp.status_code == 201, resp.text
            eve = resp.json()
            assert eve["name"] == "Eve"
            assert eve["country_id"] == [france.id, "France"]
            print("POST /api/records ->", eve)

            # Patch
            resp = client.patch(
                f"/api/records/{eve['id']}",
                params={"model": "res.partner"},
                json={"name": "Evelyn", "age": 33},
            )
            assert resp.status_code == 200, resp.text
            evelyn = resp.json()
            assert evelyn["name"] == "Evelyn" and evelyn["age"] == 33
            print("PATCH /api/records/{id} ->", evelyn)

            # Delete
            resp = client.delete(
                f"/api/records/{eve['id']}",
                params={"model": "res.partner"},
            )
            assert resp.status_code == 204, resp.text
            # 404 on missing record
            resp = client.delete(
                f"/api/records/{eve['id']}",
                params={"model": "res.partner"},
            )
            assert resp.status_code == 404

            # ----- B.3: HTMX inline-edit flow -----
            # Pull the edit-row fragment for Alice; should include inputs.
            resp = client.get(
                f"/web/records/partners/partner.list/row/{alice["id"]}/edit"
            )
            assert resp.status_code == 200, resp.text
            edit_html = resp.text
            assert 'name="name"' in edit_html
            assert 'value="Alice"' in edit_html
            # Many2one rendered as a <select>; France should be the
            # selected option.
            assert "<select" in edit_html
            assert f'value="{france.id}" selected' in edit_html
            # Save button has hx-post to the row's save endpoint.
            assert f"row/{alice['id']}" in edit_html
            print("inline-edit row fragment served with form controls")

            # Save: post form-encoded updates, expect display row back.
            resp = client.post(
                f"/web/records/partners/partner.list/row/{alice["id"]}",
                data={
                    "name": "Alicia Doe",
                    "code": "ALI-1",
                    "country_id": str(france.id),
                    # active is a Boolean — hidden "" + checked "on"
                    "active": ["", "on"],
                },
            )
            assert resp.status_code == 200, resp.text
            saved = resp.text
            # Display-mode row: Edit/Delete buttons, no <input>s.
            assert "<input" not in saved
            assert "Alicia Doe" in saved
            print("inline save returned updated display row")

            # GET the display row by id (cancel path returns this).
            resp = client.get(
                f"/web/records/partners/partner.list/row/{alice["id"]}"
            )
            assert "Alicia Doe" in resp.text

            # "+ New" -> empty edit row.
            resp = client.get("/web/records/partners/partner.list/new")
            assert resp.status_code == 200, resp.text
            new_row = resp.text
            assert 'name="name"' in new_row
            assert "Create" in new_row
            print("inline-create row fragment served")

            # POST a brand-new partner via the create endpoint.
            resp = client.post(
                "/web/records/partners/partner.list",
                data={
                    "name": "Frank",
                    "code": "FRA-X",
                    "country_id": str(japan.id),
                    "active": ["", "on"],
                },
            )
            assert resp.status_code == 200, resp.text
            created = resp.text
            assert "Frank" in created
            assert "<input" not in created  # display row, not edit

            # DELETE: empty body on success, then 404 on repeat.
            count_before = client.get("/api/records", params={"model": "res.partner"}).json()["count"]
            # Find Frank's id from the create response (parse out data-record-id)
            import re
            m = re.search(r'data-record-id="(\d+)"', created)
            assert m, created
            frank_id = int(m.group(1))
            resp = client.delete(
                f"/web/records/partners/partner.list/row/{frank_id}"
            )
            assert resp.status_code == 200, resp.text
            assert resp.text == ""
            count_after = client.get("/api/records", params={"model": "res.partner"}).json()["count"]
            assert count_after == count_before - 1, (count_before, count_after)
            print("inline delete removed the row")

            # ----- B.4: form view -----
            # Resolved form arch comes back with normalized fields.
            resp = client.get("/api/views/partners/partner.form")
            assert resp.status_code == 200, resp.text
            form_arch = resp.json()["arch"]
            assert resp.json()["view_type"] == "form"
            section_names = [s["name"] for s in form_arch["sections"]]
            assert section_names == ["identity", "profile", "relations"]
            # Strings in each section's fields were promoted to dicts.
            id_fields = [f["name"] for f in form_arch["sections"][0]["fields"]]
            assert id_fields == ["name", "code"]

            # Form display: full HTML page when no HX-Request header.
            resp = client.get(f"/web/views/partners/partner.form/record/{alice['id']}")
            assert resp.status_code == 200, resp.text
            page = resp.text
            assert "cdn.tailwindcss.com" in page
            assert "<fieldset" in page
            assert "Identity" in page
            # `Profile` was renamed to `Demographics` by partners_pro's
            # form-view inheritance (verified explicitly below).
            assert "Demographics" in page
            # Display mode shows values, not <input>s for stored fields.
            assert "Alicia Doe" in page
            # Edit button targets the edit URL.
            assert f"record/{alice['id']}/edit" in page

            # Form edit: HX-Request header returns body fragment only.
            resp = client.get(
                f"/web/views/partners/partner.form/record/{alice['id']}/edit",
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200, resp.text
            frag = resp.text
            assert "<html" not in frag         # body fragment only
            assert 'name="name"' in frag        # input present
            assert 'value="Alicia Doe"' in frag
            assert "<select" in frag            # Many2one
            print("form display + edit fragments render")

            # Save: POST form-encoded to the record URL.
            resp = client.post(
                f"/web/views/partners/partner.form/record/{alice['id']}",
                data={
                    "name": "Alice X",
                    "code": "ALI-1",
                    "age": "31",
                    "country_id": str(france.id),
                    "parent_id": "",
                    "active": ["", "on"],
                },
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200, resp.text
            saved = resp.text
            assert "Alice X" in saved
            assert "<input" not in saved       # back to display mode
            # Verify the write actually landed via /api/records too.
            resp = client.get(
                f"/api/records",
                params={"model": "res.partner",
                        "domain": f'[["id","=",{alice["id"]}]]',
                        "fields": "name,age"},
            )
            rec = resp.json()["records"][0]
            assert rec["name"] == "Alice X" and rec["age"] == 31
            print("form save persisted through to JSON read")

            # Form new: empty edit shell.
            resp = client.get(
                "/web/views/partners/partner.form/new",
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200, resp.text
            # Body-only fragment because HX-Request: true.
            assert 'name="name"' in resp.text
            # Title shows "New res.partner"
            assert "New res.partner" in resp.text
            print("form new renders empty edit shell")

            # Section-level inheritance: partners_pro patched the form
            # too (renamed Profile -> Demographics; dropped parent_id;
            # widget-hinted active).
            arch = client.get("/api/views/partners/partner.form").json()["arch"]
            section_titles = [s["title"] for s in arch["sections"]]
            assert "Demographics" in section_titles, section_titles
            profile = next(s for s in arch["sections"] if s["title"] == "Demographics")
            profile_fields = [f["name"] for f in profile["fields"]]
            assert "parent_id" not in profile_fields, profile_fields
            active = next(f for f in profile["fields"] if f["name"] == "active")
            assert active.get("widget") == "toggle"
            print("section-level inheritance applied to form view")

            # ----- B.5: kanban view -----
            # Arch normalization: badges with string entries get
            # promoted to {"name": str} dicts.
            resp = client.get("/api/views/partners/partner.kanban")
            assert resp.status_code == 200, resp.text
            kanban_arch = resp.json()["arch"]
            assert resp.json()["view_type"] == "kanban"
            badge_names = [b["name"] for b in kanban_arch["card"]["badges"]]
            assert badge_names == ["active", "tag_ids"]
            # Widget hint preserved on the dict form.
            active_badge = kanban_arch["card"]["badges"][0]
            assert active_badge.get("widget") == "toggle"
            assert kanban_arch["group_by"] == "country_id"
            assert kanban_arch["form_view"] == "partner.form"

            # Kanban page renders columns grouped by country.
            resp = client.get("/web/views/partners/partner.kanban")
            assert resp.status_code == 200, resp.text
            page = resp.text
            # Three groups: France, Japan, "(no value)" for Carol who has
            # no country.
            assert "France" in page
            assert "Japan" in page
            assert "(no value)" in page
            # Each card links to the form view for the same model.
            assert "/web/views/partners/partner.form/record/" in page
            # data-record-id attributes match every record.
            import re as _re
            card_ids = set(_re.findall(r'data-record-id="(\d+)"', page))
            partner_ids = {p["id"] for p in client.get(
                "/api/records", params={"model": "res.partner"}
            ).json()["records"]}
            assert card_ids == {str(pid) for pid in partner_ids}, (card_ids, partner_ids)
            print("kanban page renders grouped cards with form-view links")


def _drop_known_tables(conn):
    """Tear down tables we expect to own. Idempotent."""
    tables = [
        "res_partner_res_tag_rel",
        "res_partner",
        "res_tag",
        "res_country",
        "res_region",
        "ir_ui_view",
        "ir_module",
    ]
    for t in tables:
        conn.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')


if __name__ == "__main__":
    main()
