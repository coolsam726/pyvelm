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
        app = create_app(reg, pool, module_roots=[MODULES_ROOT])
        with TestClient(app) as client:
            # Default identity for the bulk of the smoke test is the
            # superuser. ACL-specific assertions further down construct
            # additional clients with manager / no auth.
            client.auth = ("admin", "admin")
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
            # Print the fields_by_name before asserting so we can see the actual structure in the test output if it doesn't match.
            print("Fields by name:", list(fields_by_name))
            assert list(fields_by_name) == [
                "name", "code","company_id", "country_id", "tag_ids", "active",
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
            assert "/web/static/dist/pyvelm.css" in html  # locally built CSS
            assert "htmx.org" in html                       # HTMX script tag
            assert "alpinejs" in html                       # Alpine for sidebar/dropdowns
            assert "flowbite" in html                       # Flowbite component JS
            assert 'id="pv-table-container"' in html
            assert "ALI-1" in html                          # Alice's code first page
            # Toggle widget for `active` — green track when value is True.
            assert "bg-green-500" in html
            # Pagination controls present because total > page_size.
            assert 'id="pv-pagination"' in html
            assert "pvList" in html                          # Alpine DataTable component
            assert "htmx:confirm" in html                    # styled confirm interceptor
            # Slice 1 of the Odoo-style search bar: per-column filter
            # row is gone; the chips-driven search shell takes its place.
            assert "data-pv-search-bar" in html
            assert "data-pv-filter-row" not in html

            # New chip-list filter wire format: each filter is a
            # `{field, op, value}` entry. Driving the same constraint
            # the per-column filter used to handle.
            import json as _json
            chip_filters = _json.dumps([
                {"field": "country_id", "op": "ilike", "value": "France"}
            ])
            resp = client.get(
                "/web/views/partners/partner.list",
                params={"filters": chip_filters},
            )
            assert resp.status_code == 200, resp.text
            assert "Alice" in resp.text and "Bob" not in resp.text
            # Legacy dict-form `{field: value}` URL still parses for
            # already-bookmarked deep links.
            resp_legacy = client.get(
                "/web/views/partners/partner.list",
                params={"filters": '{"country_id": "France"}'},
            )
            assert resp_legacy.status_code == 200
            assert "Alice" in resp_legacy.text and "Bob" not in resp_legacy.text
            print("central search bar: chip filters work, legacy URLs preserved")

            # Slice 2: Filter By / Group By dropdown is wired up and the
            # group_by URL param round-trips through the server.
            assert "data-pv-filter-panel" in html
            assert "Filter By" in html and "Group By" in html
            # Headers metadata is bootstrapped into the page so the
            # Alpine component can render Filter By / Group By items.
            assert '"filter_kind"' in html
            assert '"group_kind"' in html
            resp = client.get(
                "/web/views/partners/partner.list",
                params={"group_by": "country_id"},
            )
            assert resp.status_code == 200, resp.text
            # The group-by survives the round-trip into the bootstrap cfg.
            assert 'groupBy: "country_id"' in resp.text
            # Unknown / ungroupable columns are silently dropped (validated
            # against the headers metadata).
            resp_bad = client.get(
                "/web/views/partners/partner.list",
                params={"group_by": "not_a_field"},
            )
            assert resp_bad.status_code == 200
            assert 'groupBy: ""' in resp_bad.text
            print("filter dropdown rendered; group_by param validated")

            # Slice 3: grouping renders collapsible group headers and
            # disables pagination. Alice/Bob have a country_id set,
            # Carol doesn't — so we expect "France", "Japan", "(none)"
            # buckets in the markup.
            resp = client.get(
                "/web/views/partners/partner.list",
                params={"group_by": "country_id", "order": "id ASC"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.text
            # Group header carries the value + count.
            assert "France" in body and "Japan" in body and "(none)" in body
            # Each group header opens an Alpine scope.
            assert 'x-data="{ open: true }"' in body
            # Pagination row is suppressed when total_pages == 1.
            assert "pv-pagination" in body  # container still present
            print("group_by renders bucketed list with collapsible headers")

            # Slice 1 of the Apps catalog: every module discovered on
            # disk is shown with state + version metadata. All five
            # example modules are installed by the seeding step at the
            # top of basic.py, so every card lands in "Installed" state.
            resp = client.get("/web/apps")
            assert resp.status_code == 200, resp.text
            body = resp.text
            for mod in ("base", "admin", "partners", "crm", "partners_pro"):
                assert f'data-pv-app="{mod}"' in body, f"{mod} missing"
            # Categories defined in the manifests render as section
            # headers grouping the cards.
            assert "System" in body and "Business" in body
            # Manifest SUMMARY surfaces in the card body.
            assert "Sales pipeline" in body
            # Installed badge appears (all modules pre-installed in test).
            assert "Installed" in body
            print("Apps catalog renders all modules with category + summary")

            # Slice 2: upgrade action wires loader.install end-to-end
            # through the HTTP layer. Simulate a stale install of `base`
            # at 0.7.0 — the on-disk manifest is 0.8.0 — then POST the
            # upgrade endpoint and assert the version row caught up.
            with pool.connection() as side_conn:
                side_conn.execute(
                    "UPDATE ir_module SET version = '0.7.0' WHERE name = 'base'"
                )
            r_no_follow = TestClient(app, follow_redirects=False)
            r_no_follow.auth = ("admin", "admin")
            r = r_no_follow.post("/web/apps/base/upgrade",
                                 headers={"HX-Request": "true"})
            assert r.status_code == 204, (r.status_code, r.text)
            assert r.headers.get("HX-Redirect") == "/web/apps"
            with pool.connection() as side_conn:
                row = side_conn.execute(
                    "SELECT version FROM ir_module WHERE name = 'base'"
                ).fetchone()
            assert row == ("0.8.0",), row

            # Non-superuser is rejected — install / upgrade is admin-only
            # since it executes install_hook code and DDL.
            anon = TestClient(app)
            anon.auth = ("manager", "manager")
            r_denied = anon.post("/web/apps/base/upgrade")
            assert r_denied.status_code == 403, (r_denied.status_code, r_denied.text)
            print("apps upgrade: superuser-gated, version row rolls forward")

            # Slice 3: uninstall flow has a dry-run preview that
            # surfaces blockers before any destructive action runs.
            base_pv = client.get("/web/apps/base/uninstall-preview").json()
            assert base_pv["blockers"], "base must be uninstall-blocked"
            pp_pv = client.get("/web/apps/partners_pro/uninstall-preview").json()
            assert any("_inherit" in b for b in pp_pv["blockers"]), pp_pv
            partners_pv = client.get("/web/apps/partners/uninstall-preview").json()
            assert any("crm" in b for b in partners_pv["blockers"]), partners_pv
            # crm has no reverse-deps and doesn't extend models, so
            # uninstall should be allowed and list crm_lead for drop.
            crm_pv = client.get("/web/apps/crm/uninstall-preview").json()
            assert not crm_pv["blockers"], crm_pv
            assert "crm_lead" in crm_pv["tables"], crm_pv
            assert crm_pv["views"] > 0  # crm ships list/form/kanban views

            # Execute the uninstall and verify the side effects landed.
            r_no_follow.auth = ("admin", "admin")
            r_uninst = r_no_follow.post(
                "/web/apps/crm/uninstall",
                headers={"HX-Request": "true"},
            )
            assert r_uninst.status_code == 204, r_uninst.text
            assert r_uninst.headers.get("HX-Redirect") == "/web/apps"
            with pool.connection() as side_conn:
                # ir_module row gone.
                row = side_conn.execute(
                    "SELECT name FROM ir_module WHERE name = 'crm'"
                ).fetchone()
                assert row is None
                # crm_lead table dropped.
                r2 = side_conn.execute(
                    "SELECT to_regclass('crm_lead')"
                ).fetchone()
                assert r2 == (None,), r2
                # ir.ui.view rows for module='crm' gone.
                r3 = side_conn.execute(
                    "SELECT COUNT(*) FROM ir_ui_view WHERE module = 'crm'"
                ).fetchone()
                assert r3 == (0,), r3
            print("apps uninstall: preview blockers + transactional cleanup work")
            # Sidebar entries come from ir.ui.menu — base ships Dashboard,
            # admin ships Settings/Security/Workflows, partners ships Apps,
            # crm ships CRM. If any of these are missing, the sync broke.
            for label in ("Dashboard", "Apps", "Settings", "Security",
                          "Workflows", "CRM", "Pipeline", "All Leads",
                          "Partners", "Companies"):
                assert label in html, f"sidebar missing {label!r}"
            print("HTML list view renders with Tailwind+Flowbite + pagination")
            print("Sidebar populated from ir.ui.menu (all module entries present)")

            # 7. HTMX fragment endpoint returns just <tr>s + OOB pagination.
            resp = client.get(
                "/web/records/partners/partner.list",
                params={"page": 1, "page_size": 2},
            )
            assert resp.status_code == 200, resp.text
            frag = resp.text
            # No <html>/<body> in a fragment response.
            assert "<html" not in frag
            assert "<tr" in frag
            # OOB pagination swap is present in the fragment.
            assert 'hx-swap-oob' in frag
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
            # Many2one is now a combobox: hidden input carries the id;
            # an `x-data='pvM2o(...)'` wrapper drives the search dropdown.
            assert 'pvM2o(' in edit_html
            assert "/api/m2o/search?model=res.country" in edit_html
            # The hidden input pre-fills with the current Many2one id
            # (no `selected` option to assert since there's no <select>).
            assert f':value="value === null ? \'\' : value"' in edit_html
            # Save button has hx-post to the row's save endpoint.
            assert f"row/{alice['id']}" in edit_html
            print("inline-edit row fragment served with combobox + form controls")

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
            assert section_names == ["identity", "profile", "relations", "vip"]
            # Strings in each section's fields were promoted to dicts.
            id_fields = [f["name"] for f in form_arch["sections"][0]["fields"]]
            assert id_fields == ["name", "code"]

            # Form display: full HTML page when no HX-Request header.
            resp = client.get(f"/web/views/partners/partner.form/record/{alice['id']}")
            assert resp.status_code == 200, resp.text
            page = resp.text
            assert "/web/static/dist/pyvelm.css" in page
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
            # Many2one renders as the pvM2o combobox now.
            assert "pvM2o(" in frag
            # Edit mode opts the form into the navigation autosave —
            # any link click while dirty triggers a POST to this URL.
            assert "data-pv-autosave=" in frag, frag[:1000]
            assert f"/record/{alice['id']}" in frag
            print("form display + edit fragments render (autosave wired)")

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
            # Title shows "New Partner" (humanised from res.partner)
            assert "New Partner" in resp.text
            print("form new renders empty edit shell")

            # ----- B.5 / Stage 5: ACL behavior -----
            # Mark Carol inactive so the record rule for Partner Manager
            # (active=True only) actually filters her out.
            r = client.get(
                "/api/records",
                params={"model": "res.partner",
                        "domain": '[["name", "=", "Carol"]]',
                        "fields": "id,name,active"},
            )
            assert r.status_code == 200, (r.status_code, r.text)
            carol_q = r.json()
            assert carol_q["count"] == 1, carol_q
            carol_id = carol_q["records"][0]["id"]
            r = client.patch(
                f"/api/records/{carol_id}",
                params={"model": "res.partner"},
                json={"active": False},
            )
            assert r.status_code == 200, r.text

            # Anonymous: 401 with a Basic challenge on partner reads.
            anon = TestClient(app)
            r = anon.get("/api/records", params={"model": "res.partner"})
            assert r.status_code == 401, r.text
            assert r.headers.get("www-authenticate", "").lower().startswith("basic")
            # But countries/regions are public-readable (granted to
            # group_id=None by the partners install hook).
            r = anon.get("/api/records", params={"model": "res.country"})
            assert r.status_code == 200, r.text
            print("anonymous: 401 on partners, 200 on countries")

            # Wrong password: still anonymous (no auth-by-implication).
            bad = TestClient(app); bad.auth = ("manager", "wrong")
            r = bad.get("/api/records", params={"model": "res.partner"})
            assert r.status_code == 401, r.text

            # Partner Manager: sees only active partners (record rule).
            mgr = TestClient(app); mgr.auth = ("manager", "manager")
            r = mgr.get(
                "/api/records",
                params={"model": "res.partner",
                        "fields": "name,active",
                        "order": '"id" ASC'},
            )
            assert r.status_code == 200, r.text
            mgr_view = r.json()
            names_seen = [rec["name"] for rec in mgr_view["records"]]
            # Carol was marked inactive above -> hidden from Manager.
            assert "Carol" not in names_seen, names_seen
            # Active partners (Alice X, Bob, Dave) ARE visible.
            assert "Alice X" in names_seen
            print("Partner Manager sees:", names_seen)

            # Manager can write to a visible partner...
            alice_q = mgr.get(
                "/api/records",
                params={"model": "res.partner",
                        "domain": '[["name", "=", "Alice X"]]',
                        "fields": "id"},
            ).json()
            alice_id_mgr = alice_q["records"][0]["id"]
            r = mgr.patch(
                f"/api/records/{alice_id_mgr}",
                params={"model": "res.partner"},
                json={"age": 32},
            )
            assert r.status_code == 200, r.text
            # ... but cannot create or unlink (perms not granted).
            r = mgr.post(
                "/api/records",
                params={"model": "res.partner"},
                json={"name": "Sneaky"},
            )
            assert r.status_code == 403, (r.status_code, r.text)
            r = mgr.delete(
                f"/api/records/{alice_id_mgr}",
                params={"model": "res.partner"},
            )
            assert r.status_code == 403, (r.status_code, r.text)
            print("Partner Manager: write OK, create/unlink denied")

            # Admin remains uncapped: full CRUD goes through. Restore
            # Carol so later assertions keep working.
            r = client.patch(
                f"/api/records/{carol_id}",
                params={"model": "res.partner"},
                json={"active": True},
            )
            assert r.status_code == 200, r.text

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

            # ----- Stage 5 Slice B: session cookies + form login -----

            # GET /login renders the form (no cookie yet).
            anon2 = TestClient(app, follow_redirects=False)
            r = anon2.get("/login")
            assert r.status_code == 200, r.text
            assert 'name="login"' in r.text
            assert 'name="password"' in r.text
            print("GET /login: login form rendered")

            # POST /login with bad credentials returns 401 + error msg.
            r = anon2.post(
                "/login",
                data={"login": "admin", "password": "WRONG", "next": "/"},
            )
            assert r.status_code == 401, r.status_code
            assert "Invalid username or password" in r.text
            print("POST /login bad creds: 401 with error message")

            # POST /login with correct credentials: 303 redirect + cookie.
            r = anon2.post(
                "/login",
                data={"login": "admin", "password": "admin", "next": "/"},
            )
            assert r.status_code == 303, (r.status_code, r.text)
            session_cookie = r.cookies.get("pyvelm_session")
            assert session_cookie, "expected pyvelm_session cookie in response"
            print("POST /login good creds: 303 redirect + session cookie set")

            # Cookie authenticates subsequent requests (no Basic header).
            cookie_client = TestClient(app, follow_redirects=False)
            cookie_client.cookies.set("pyvelm_session", session_cookie)
            r = cookie_client.get(
                "/api/records", params={"model": "res.partner", "fields": "name"}
            )
            assert r.status_code == 200, (r.status_code, r.text)
            print("session cookie authenticates API requests")

            # GET /login with a valid cookie redirects away (no re-login).
            r = cookie_client.get("/login?next=/web/")
            assert r.status_code == 302, r.status_code
            print("GET /login with active session: redirect away")

            # POST /logout clears cookie + revokes token in DB.
            r = cookie_client.post("/logout")
            assert r.status_code == 303, r.status_code
            assert "pyvelm_session" not in r.cookies or r.cookies["pyvelm_session"] == ""
            print("POST /logout: 303 redirect + cookie cleared")

            # After logout, the old token no longer grants access.
            stale_client = TestClient(app, follow_redirects=False)
            stale_client.cookies.set("pyvelm_session", session_cookie)
            r = stale_client.get(
                "/api/records", params={"model": "res.partner"}
            )
            assert r.status_code == 401, (r.status_code, r.text)
            print("stale token rejected after logout")

            # Logout sets Clear-Site-Data so the browser drops bfcache —
            # otherwise hitting Back would show the previously-rendered
            # authenticated page even though the server has revoked
            # the session.
            no_follow = TestClient(app, follow_redirects=False)
            r = no_follow.post("/logout")
            assert r.headers.get("Clear-Site-Data"), "logout missing Clear-Site-Data"
            print("logout: Clear-Site-Data sent for bfcache invalidation")

            # The HTMX inline-edit / save endpoints reject unauthenticated
            # callers — even when the browser's back-cache hands the user
            # a stale list page, clicking Edit/Save now triggers a
            # client-side redirect to /login.
            r = stale_client.get(
                "/web/records/partners/partner.list/row/1/edit",
                headers={"HX-Request": "true"},
            )
            assert r.headers.get("HX-Redirect", "").startswith("/login"), (
                r.status_code, r.headers, r.text,
            )
            print("HTMX edit endpoint redirects via HX-Redirect after logout")
            r = stale_client.post(
                "/web/records/partners/partner.list/row/1",
                headers={"HX-Request": "true"},
                data={"name": "Hacked"},
            )
            assert r.headers.get("HX-Redirect", "").startswith("/login"), (
                r.status_code, r.headers, r.text,
            )
            print("HTMX save endpoint rejects unauthenticated POST after logout")

            # ----- Stage 5 Slice C: admin module -----
            # The admin module adds 8 views (list+form for each ACL
            # model) and grants Admin full CRUD on those models.

            # Admin dashboard renders for authenticated admin.
            r = client.get("/web/admin")
            assert r.status_code == 200, r.text
            assert "Groups" in r.text
            assert "Users" in r.text
            assert "Access Control" in r.text
            assert "Record Rules" in r.text
            print("/web/admin: dashboard renders for admin")

            # Unauthenticated request redirects to /login.
            anon3 = TestClient(app, follow_redirects=False)
            r = anon3.get("/web/admin")
            assert r.status_code == 302, r.status_code
            assert "/login" in r.headers["location"]
            print("/web/admin: unauthenticated redirects to login")

            # The 4 list views are accessible and return 200.
            for view_name in ("group.list", "user.list", "access.list", "rule.list"):
                r = client.get(f"/web/views/admin/{view_name}")
                assert r.status_code == 200, (view_name, r.status_code, r.text)
            print("admin list views: all 4 render OK")

            # The 4 form views are accessible for an existing record.
            # Use id=1 for the admin group (first record seeded by base install hook).
            for view_name in ("group.form", "user.form"):
                r = client.get(f"/web/views/admin/{view_name}/record/1")
                assert r.status_code == 200, (view_name, r.status_code, r.text)
            print("admin form views: record display renders OK")

            # Admin can create a group via the JSON API (ACL grant is active).
            r = client.post(
                "/api/records",
                params={"model": "res.groups"},
                json={"name": "Test Group"},
            )
            assert r.status_code == 201, (r.status_code, r.text)
            test_group_id = r.json()["id"]
            print("admin: create res.groups via API OK")

            # Admin can delete it too.
            r = client.delete(
                f"/api/records/{test_group_id}",
                params={"model": "res.groups"},
            )
            assert r.status_code == 204, (r.status_code, r.text)
            print("admin: delete res.groups via API OK")

            # ===== Stage 6: workflows =====
            # These tests exercise the ORM directly (not via HTTP), so we
            # need a live connection from the pool.  Grab one for the
            # duration of the Stage 6 section.
            with pool.connection() as wf_conn:
                from pyvelm import Environment as _Env
                wf_env = _Env(wf_conn, registry=reg, uid=1)

                # ----- Slice A: server actions -----

                # action_type=write: set active=False on all partners.
                act_write = wf_env["ir.actions.server"].create({
                    "name": "Deactivate all partners",
                    "model": "res.partner",
                    "action_type": "write",
                    "vals_json": '{"active": false}',
                })
                all_partners = wf_env["res.partner"].search([])
                with wf_env.transaction():
                    act_write.run(all_partners)
                inactive = wf_env["res.partner"].search([("active", "=", False)])
                assert len(inactive) == len(all_partners), inactive
                # Restore
                with wf_env.transaction():
                    inactive.write({"active": True})
                print("server action write: deactivate/restore all partners OK")

                # action_type=create: create a partner.
                act_create = wf_env["ir.actions.server"].create({
                    "name": "Create test partner",
                    "model": "res.partner",
                    "action_type": "create",
                    "vals_json": '{"name": "Action Partner"}',
                })
                with wf_env.transaction():
                    act_create.run()
                ap = wf_env["res.partner"].search([("name", "=", "Action Partner")])
                assert ap, "expected created record"
                print("server action create: new partner via action OK")

                # action_type=unlink: delete that partner.
                act_unlink = wf_env["ir.actions.server"].create({
                    "name": "Delete action partner",
                    "model": "res.partner",
                    "action_type": "unlink",
                })
                with wf_env.transaction():
                    act_unlink.run(ap)
                gone = wf_env["res.partner"].search([("name", "=", "Action Partner")])
                assert not gone, "expected record to be deleted"
                print("server action unlink: deleted partner via action OK")

                # action_type=code: exec arbitrary Python via direct call.
                results: list = []
                act_code = wf_env["ir.actions.server"].create({
                    "name": "Code action",
                    "model": "res.partner",
                    "action_type": "code",
                    "code": "results.append(len(records))",
                })
                code_partners = wf_env["res.partner"].search([], limit=2)
                code_src = act_code.code
                _g: dict = {}
                _l: dict = {
                    "env": wf_env,
                    "records": code_partners,
                    "action": act_code,
                    "results": results,
                }
                exec(compile(code_src, "<test>", "exec"), _g, _l)  # noqa: S102
                assert results == [len(code_partners)], results
                print("server action code: executed Python snippet OK")

                # ----- Slice B: automated actions -----

                log_action = wf_env["ir.actions.server"].create({
                    "name": "Log creates",
                    "model": "res.partner",
                    "action_type": "code",
                    "code": "pass",   # side-effect tested via no-error firing
                })
                wf_env["base.automation"].create({
                    "name": "On partner create",
                    "model": "res.partner",
                    "trigger": "on_create",
                    "action_id": log_action,
                    "active": True,
                })
                # Trigger fires on create without raising.
                with wf_env.transaction():
                    new_p = wf_env["res.partner"].create({"name": "AutoTrigger"})
                assert new_p, "partner created"
                print("automated action: on_create trigger fires without error OK")

                stamp_action = wf_env["ir.actions.server"].create({
                    "name": "Track writes",
                    "model": "res.partner",
                    "action_type": "code",
                    "code": "pass",
                })
                auto_rule = wf_env["base.automation"].create({
                    "name": "On partner write",
                    "model": "res.partner",
                    "trigger": "on_write",
                    "action_id": stamp_action,
                    "active": True,
                })
                with wf_env.transaction():
                    new_p.write({"name": "AutoTrigger2"})
                print("automated action: on_write trigger fires without error OK")

                # Deactivate and verify no crash afterward.
                with wf_env.transaction():
                    auto_rule.write({"active": False})
                print("automated action: deactivate rule OK")

                # ----- Slice C: scheduled jobs -----
                from datetime import datetime as _dt, timedelta as _td
                from pyvelm.cron import CronJob

                tick_action = wf_env["ir.actions.server"].create({
                    "name": "Cron tick",
                    "model": "res.partner",
                    "action_type": "code",
                    "code": "pass",
                })
                past = _dt.utcnow() - _td(seconds=1)
                cron = wf_env["ir.cron"].create({
                    "name": "Test cron",
                    "action_id": tick_action,
                    "interval_number": 1,
                    "interval_type": "hours",
                    "nextcall": past,
                    "active": True,
                })
                ran = CronJob.run_due(wf_env)
                assert "Test cron" in ran, ran
                wf_env.cache.invalidate(model_name="ir.cron", ids=[cron.id])
                new_next = cron.nextcall
                assert new_next > _dt.utcnow(), f"nextcall not advanced: {new_next}"
                print("cron: due job runs and nextcall advances OK")

                future = _dt.utcnow() + _td(hours=1)
                with wf_env.transaction():
                    cron.write({"nextcall": future})
                wf_env.cache.invalidate(model_name="ir.cron", ids=[cron.id])
                ran2 = CronJob.run_due(wf_env)
                assert "Test cron" not in ran2, ran2
                print("cron: future job skipped OK")

                # ----- Slice D: mail threads -----
                alice = wf_env["res.partner"].search([], limit=1)
                assert alice, "need a partner for mail test"
                msg = wf_env["mail.message"].create({
                    "model": "res.partner",
                    "res_id": alice.id,
                    "body": "Hello from mail thread!",
                    "message_type": "comment",
                    "author_id": wf_env.uid,
                })
                assert msg.id, "message not created"
                msgs = wf_env["mail.message"].search([
                    ("model", "=", "res.partner"),
                    ("res_id", "=", alice.id),
                ])
                assert len(msgs) >= 1
                print("mail.message: posted and retrieved message OK")

                raw_ids = wf_env["mail.message"].search([
                    ("model", "=", "res.partner"),
                    ("res_id", "=", alice.id),
                ]).ids
                assert msg.id in raw_ids
                print("mail thread: message_ids query OK")

            # ===== Stage 7: _inherit model extension =====
            # partners_pro defines PartnerPro(_inherit="res.partner")
            # which adds `vip_note` and overrides `_compute_display_name`.
            with pool.connection() as s7_conn:
                from pyvelm import Environment as _Env7
                s7_env = _Env7(s7_conn, registry=reg, uid=1)

                # The extended class IS the registry entry.
                extended_cls = reg["res.partner"]
                assert "vip_note" in extended_cls._fields, (
                    "_inherit must have added vip_note to res.partner"
                )
                print("_inherit: vip_note field present on res.partner OK")

                # Write vip_note and read it back.
                partner_rec = s7_env["res.partner"].search([], limit=1)
                assert partner_rec, "need at least one partner"
                with s7_env.transaction():
                    partner_rec.write({"vip_note": "Top tier"})
                s7_env.cache.invalidate(model_name="res.partner", ids=[partner_rec.id])
                assert partner_rec.vip_note == "Top tier", partner_rec.vip_note
                print("_inherit: vip_note write/read OK")

                # display_name should carry the ★ prefix for VIP partners.
                s7_env.cache.invalidate(model_name="res.partner", ids=[partner_rec.id])
                dn = partner_rec.display_name
                assert dn.startswith("★ "), (
                    f"expected VIP prefix in display_name, got {dn!r}"
                )
                print("_inherit: overridden _compute_display_name applies ★ prefix OK")

                # Partners without a vip_note get the original display_name.
                no_vip = s7_env["res.partner"].search(
                    [("vip_note", "=", None)], limit=1
                )
                if no_vip:
                    dn_plain = no_vip.display_name
                    assert not dn_plain.startswith("★"), (
                        f"non-VIP partner must not have ★ prefix: {dn_plain!r}"
                    )
                    print("_inherit: non-VIP partner keeps plain display_name OK")

                # super() chain: verify the name portion is still correct.
                assert partner_rec.name in dn, (
                    f"partner name {partner_rec.name!r} missing from {dn!r}"
                )
                print("_inherit: super() chained correctly in display_name OK")

            # ===== Stage 8: multi-company =====
            with pool.connection() as s8_conn:
                from pyvelm import Environment as _Env8
                s8_env = _Env8(s8_conn, registry=reg, uid=1)

                # Slice A — res.company model seeded by install hook.
                assert "res.company" in reg, "res.company not in registry"
                companies = s8_env["res.company"].search([])
                assert companies, "install hook must seed at least one company"
                my_company = list(companies)[0]
                print(f"_inherit: res.company seeded: {my_company.name!r} (id={my_company.id})")

                # uid=1 (superuser) has company_id set from the install hook.
                admin_user = s8_env["res.users"].browse(1)
                assert admin_user.company_id, "uid=1 must have company_id set"
                print(f"multi-company: uid=1 company_id={admin_user.company_id.id} OK")

                # Slice B — env.company_id / with_company().
                assert s8_env.company_id is None, "fresh env has no company scope"
                scoped_env = s8_env.with_company(my_company.id)
                assert scoped_env.company_id == my_company.id
                print("multi-company: env.with_company() sets company_id OK")

                # Create a second company to test cross-tenant isolation.
                with s8_env.transaction():
                    company_b = s8_env["res.company"].create(
                        {"name": "Contoso Ltd", "active": True}
                    )
                print(f"multi-company: created second company {company_b.name!r} (id={company_b.id})")

                # Assign one partner to company A, another to company B.
                partners = list(s8_env["res.partner"].search([], limit=2))
                assert len(partners) >= 2, "need at least 2 partners for isolation test"
                p_a, p_b = partners[0], partners[1]
                with s8_env.transaction():
                    p_a.write({"company_id": my_company})
                    p_b.write({"company_id": company_b})
                s8_env.cache.invalidate(model_name="res.partner")
                print("multi-company: assigned partners to separate companies OK")

                # 0.7.0: the company filter applies to EVERYONE, including
                # uid=1, when env.company_id is set on a `_company_scoped`
                # model. To opt out, use `env.with_company(None)`.
                assert scoped_env.company_id == my_company.id
                only_a = scoped_env["res.partner"].search([])
                a_ids = set(only_a.ids)
                assert p_a.id in a_ids, "scoped search must include the company-A partner"
                assert p_b.id not in a_ids, (
                    "scoped search must hide the company-B partner — superuser bypass "
                    "of the company filter is intentionally OFF in 0.7.0"
                )
                # Without scope, superuser sees everything.
                everyone = s8_env.with_company(None)["res.partner"].search([])
                assert p_a.id in everyone.ids and p_b.id in everyone.ids
                print("multi-company: search scoping via env.company_id OK")

                # 0.7.0 standardizes on the model-level filter for company
                # scoping; the global ir.rule duplicating it has been
                # removed. Only group-scoped rules survive (partners_pro
                # ships "PM: active partners only").
                bypass_env = _Env8(s8_conn, registry=reg, uid=1)
                bypass_env._acl_bypass = True
                rules = bypass_env["ir.rule"].search([("model", "=", "res.partner")])
                rule_names = [r.name for r in rules]
                assert "res.partner: company scope" not in rule_names, (
                    "0.6.0 global company-scope rule must be pruned in 0.7.0; "
                    f"found: {rule_names}"
                )
                print(f"multi-company: {len(rules)} group-scoped ir.rule(s) (no global)")

                # Slice D — /web/switch-company and /web/companies endpoints.
                r = client.get("/web/companies")
                assert r.status_code == 200, (r.status_code, r.text)
                data = r.json()
                assert "companies" in data
                assert any(c["name"] == "My Company" for c in data["companies"])
                print("/web/companies: returns company list OK")

                # Switch to company A.
                r = client.post(
                    "/web/switch-company",
                    data={"company_id": str(my_company.id)},
                    follow_redirects=False,
                )
                assert r.status_code == 303, (r.status_code, r.text)
                assert "pyvelm_company" in r.cookies
                print("/web/switch-company: sets company cookie OK")

                # Clear scope — empty company_id value removes cookie.
                r = client.post(
                    "/web/switch-company",
                    data={"company_id": ""},
                    follow_redirects=False,
                )
                assert r.status_code == 303, (r.status_code, r.text)
                print("/web/switch-company: clear company cookie OK")


def _drop_known_tables(conn):
    """Tear down tables we expect to own. Idempotent."""
    tables = [
        "res_partner_res_tag_rel",
        "res_groups_res_users_rel",
        "res_partner",
        "res_tag",
        "res_country",
        "res_region",
        "ir_rule",
        "ir_model_access",
        "ir_ui_view",
        "ir_ui_menu",
        "res_users",
        "res_groups",
        "mail_message",
        "ir_cron",
        "base_automation",
        "ir_actions_server",
        "res_company",
        "crm_lead",
        "ir_module",
    ]
    for t in tables:
        conn.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')


if __name__ == "__main__":
    main()
