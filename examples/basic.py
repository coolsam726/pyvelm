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

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.web import create_app

load_dotenv(".env")

HERE = Path(__file__).parent
# Built-in modules (`base` + `admin`) ship with the pyvelm wheel; the
# illustrative addons (partners, partners_pro, crm) live under
# examples/modules. The smoke test discovers both.
EXAMPLE_ROOT = HERE / "modules"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [EXAMPLE_ROOT]


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

        specs = loader.load_and_install(MODULE_ROOTS, env)
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
        assert dict(rows)["partners"] == "0.3.0"

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
        app = create_app(reg, pool, module_roots=MODULE_ROOTS)
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
            # Filter toolbar: search input + state pills + category dropdown,
            # and each card carries the data-attributes that drive client-
            # side filtering.
            assert "data-pv-apps-state" in body
            assert "data-pv-app-haystack" in body
            assert "Search modules…" in body
            print("Apps catalog renders all modules with category + summary")

            # Slice 2: upgrade action wires loader.install end-to-end
            # through the HTTP layer. Simulate a stale install of `base`
            # at 0.7.0 — the on-disk manifest is 0.8.0 — then POST the
            # upgrade endpoint and assert the version row caught up.
            with pool.connection() as side_conn:
                side_conn.execute(
                    "UPDATE ir_module SET version = '0.11.0' WHERE name = 'base'"
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
            assert row == ("0.12.0",), row

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
            # Display-mode row: Edit/Delete buttons + the row-selection
            # checkbox shipped by the Nuru shell, but no edit-mode
            # text/number inputs.
            assert 'type="text"' not in saved
            assert 'type="number"' not in saved
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
            # Display row carries a row-selection checkbox + delete/edit
            # buttons — but no edit-mode text/number inputs.
            assert 'type="text"' not in created
            assert 'type="number"' not in created

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

            # Slice 1 of form-UX completeness: a parse-side validation
            # failure returns 422 + the edit form re-rendered with
            # per-field errors stamped. The save does NOT persist.
            resp_bad = client.post(
                f"/web/views/partners/partner.form/record/{alice['id']}",
                data={
                    "name": "",          # required → triggers "This field is required."
                    "code": "ALI-1",
                    "age": "not a number",  # bad Integer → triggers "Must be a whole number."
                    "country_id": str(france.id),
                    "parent_id": "",
                    "active": ["", "on"],
                },
                headers={"HX-Request": "true"},
            )
            assert resp_bad.status_code == 422, (resp_bad.status_code, resp_bad.text)
            err_body = resp_bad.text
            assert "This field is required" in err_body
            assert "Must be a whole number" in err_body
            assert "data-pv-field-error" in err_body
            # The bad save didn't land — name + age are still the saved
            # values from the previous successful write.
            check = client.get(
                "/api/records",
                params={"model": "res.partner",
                        "domain": f'[["id","=",{alice["id"]}]]',
                        "fields": "name,age"},
            ).json()["records"][0]
            assert check["name"] == "Alice X" and check["age"] == 31
            print("form validation: 422 + per-field errors, no partial write")

            # Slice 2 of form-UX: M2m chip editor for tag_ids.
            # Confirm the edit form renders the pvM2m partial wired
            # against /api/m2o/search?model=res.tag.
            resp = client.get(
                f"/web/views/partners/partner.form/record/{alice['id']}/edit",
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            frag = resp.text
            assert "pvM2m(" in frag and "model=res.tag" in frag

            # Seed a second tag to multi-select against. The Tag
            # recordset bound to the install-time connection is dead
            # by now; insert via the live pool instead.
            with pool.connection() as side_conn:
                side_conn.execute(
                    "INSERT INTO res_tag (name) VALUES ('Wholesale') "
                    "RETURNING id"
                )
                _row = side_conn.execute(
                    "SELECT id FROM res_tag WHERE name = 'Wholesale'"
                ).fetchone()
                assert _row is not None
                wholesale_id = _row[0]
            vip_id = vip.id

            # Save with both tags selected. parse_form_vals collects all
            # tag_ids form values (one per chip) into a list of ints
            # and writes them via BaseModel.write's replace semantics.
            resp_save = client.post(
                f"/web/views/partners/partner.form/record/{alice['id']}",
                data={
                    "name": "Alice X",
                    "code": "ALI-1",
                    "age": "31",
                    "country_id": str(france.id),
                    "parent_id": "",
                    "active": "on",
                    # Empty marker + two selections, mirroring what
                    # pvM2m emits from the form. httpx supports the
                    # dict[str, list[str]] form for repeated keys.
                    "tag_ids": ["", str(vip_id), str(wholesale_id)],
                },
                headers={"HX-Request": "true"},
            )
            assert resp_save.status_code == 200, resp_save.text
            with pool.connection() as side_conn:
                rows = side_conn.execute(
                    "SELECT res_tag_id FROM res_partner_res_tag_rel "
                    "WHERE res_partner_id = %s ORDER BY res_tag_id",
                    [alice["id"]],
                ).fetchall()
            tag_ids_after = [r[0] for r in rows]
            assert vip_id in tag_ids_after and wholesale_id in tag_ids_after
            assert len(tag_ids_after) == 2

            # Clearing the chip editor (only the empty marker remains
            # in the form) drops every M2m link.
            resp_clear = client.post(
                f"/web/views/partners/partner.form/record/{alice['id']}",
                data={
                    "name": "Alice X",
                    "code": "ALI-1",
                    "age": "31",
                    "country_id": str(france.id),
                    "parent_id": "",
                    "active": "on",
                    "tag_ids": "",       # marker only — nothing selected
                },
                headers={"HX-Request": "true"},
            )
            assert resp_clear.status_code == 200, resp_clear.text
            with pool.connection() as side_conn:
                cleared = side_conn.execute(
                    "SELECT COUNT(*) FROM res_partner_res_tag_rel "
                    "WHERE res_partner_id = %s",
                    [alice["id"]],
                ).fetchone()
            assert cleared == (0,), cleared
            print("M2m chip editor: multi-select + clear both write correctly")

            # Slice 3 of form-UX: drag-reorder via a sequence field.
            # tag.list ships with `arch["sequence"] = "sequence"`, so
            # the list page renders a drag-handle column and forces
            # the order to "sequence ASC".
            resp_tags = client.get("/web/views/partners/tag.list")
            assert resp_tags.status_code == 200, resp_tags.text
            tag_body = resp_tags.text
            assert "data-pv-row-handle" in tag_body
            assert "sequenceField:" in tag_body  # bootstrap cfg
            # Capture the current ids in render order.
            import re as _re
            ids_in_order = [
                int(m) for m in
                _re.findall(r'data-record-id="(\d+)"', tag_body)
            ]
            assert vip_id in ids_in_order and wholesale_id in ids_in_order
            # Issue a reorder that swaps wholesale ahead of vip.
            new_order = list(reversed(ids_in_order))
            r_reorder = client.post(
                "/web/records/partners/tag.list/reorder",
                json={"ids": new_order},
            )
            assert r_reorder.status_code == 204, r_reorder.text
            with pool.connection() as side_conn:
                stored = side_conn.execute(
                    'SELECT id, sequence FROM res_tag ORDER BY sequence ASC'
                ).fetchall()
            stored_order = [r[0] for r in stored]
            assert stored_order == new_order, (stored_order, new_order)
            # Sequence values are monotonically increasing by 10.
            seqs = [r[1] for r in stored]
            assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
            print("row reorder: drag handle present, POST /reorder rewrites sequence")

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

            # Stage 7 Slice C — predicate + wildcard target segments
            # via the `partner.form.pro.xpath` extension:
            #   - predicate: any field with widget=toggle in the
            #     profile section gets readonly=True
            #   - `**` wildcard: tag_ids gets a label without
            #     hard-coding the section path
            assert active.get("readonly") is True, active
            relations = next(s for s in arch["sections"] if s["name"] == "relations")
            tag_field = next(f for f in relations["fields"] if f["name"] == "tag_ids")
            assert tag_field.get("label") == "Tags (any section)", tag_field
            print("Slice C: predicate + `**` wildcard target segments apply")

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
            assert 'name="_csrf"' in r.text  # CSRF hidden field embedded
            print("GET /login: login form rendered")

            # The CSRF middleware set the cookie on the GET above; every
            # POST must echo it back as a header or hidden form field.
            csrf_tok = anon2.cookies.get("pyvelm_csrf")
            assert csrf_tok, "expected pyvelm_csrf cookie after GET /login"

            # POSTs with a cookie but no token are rejected — proves the
            # protection is on.
            r_no_csrf = anon2.post(
                "/login",
                data={"login": "admin", "password": "admin", "next": "/"},
            )
            assert r_no_csrf.status_code == 403, r_no_csrf.status_code
            assert "CSRF" in r_no_csrf.text
            print("POST /login without CSRF token: 403")

            # Reuse the cookie via header — proves header path works
            # alongside the form-field path used by the login template.
            r_hdr = anon2.post(
                "/login",
                data={"login": "admin", "password": "WRONG", "next": "/"},
                headers={"X-CSRF-Token": csrf_tok},
            )
            assert r_hdr.status_code == 401, r_hdr.status_code
            print("POST /login with CSRF header: accepted (header path works)")

            # Rate limit: hammer /login from a fresh client until we
            # exceed the window cap; subsequent attempts return 429.
            app.state.login_attempts.clear()
            burst = TestClient(app, follow_redirects=False)
            burst_csrf = burst.get("/login").text  # set cookie
            tok = burst.cookies.get("pyvelm_csrf")
            # 5 attempts allowed in a 5-min window.
            for i in range(5):
                rb = burst.post(
                    "/login",
                    data={"login": "nobody", "password": "x", "_csrf": tok},
                )
                assert rb.status_code in (401, 303), (i, rb.status_code)
            r_limited = burst.post(
                "/login",
                data={"login": "nobody", "password": "x", "_csrf": tok},
            )
            assert r_limited.status_code == 429, r_limited.status_code
            assert r_limited.headers.get("Retry-After")
            # Clear the bucket so the next legitimate POSTs (logout etc.)
            # below don't trip the limit.
            app.state.login_attempts.clear()
            print("POST /login rate limit: 429 + Retry-After after 5/window")

            # ----- Self-service password change -----
            # Log in fresh as a new user we control, swap the password,
            # verify the old one no longer works + the new one does.
            with pool.connection() as side_conn:
                side_conn.execute(
                    "INSERT INTO res_groups (name) VALUES ('Bench') ON CONFLICT DO NOTHING"
                )
                g_row = side_conn.execute(
                    "SELECT id FROM res_groups WHERE name = 'Bench'"
                ).fetchone()
                assert g_row is not None
                # bcrypt hash of "starter" — uses the Password field's
                # write path indirectly by storing a pre-hashed value.
                import bcrypt as _bcrypt
                hashed = _bcrypt.hashpw(b"starter", _bcrypt.gensalt()).decode("ascii")
                side_conn.execute(
                    "INSERT INTO res_users (login, name, password, active) "
                    "VALUES ('rotator', 'Rotator', %s, true)", [hashed]
                )

            rotator = TestClient(app, follow_redirects=False)
            rotator.get("/login")  # set CSRF cookie
            tok = rotator.cookies.get("pyvelm_csrf")
            r = rotator.post(
                "/login",
                data={"login": "rotator", "password": "starter",
                      "next": "/web/account/password", "_csrf": tok},
            )
            assert r.status_code == 303, (r.status_code, r.text)

            # GET the page renders fields.
            r = rotator.get("/web/account/password")
            assert r.status_code == 200, r.text
            assert 'name="current_password"' in r.text
            assert 'name="new_password"' in r.text

            # CSRF token rides through the same cookie set by the
            # earlier /login GET; the layout's JS auto-injector handles
            # this in the browser, but the test client posts plain.
            csrf_p = rotator.cookies.get("pyvelm_csrf") or ""

            # Wrong current → 422 + per-field error.
            r = rotator.post(
                "/web/account/password",
                data={"current_password": "wrong", "new_password": "newpass",
                      "confirm_password": "newpass", "_csrf": csrf_p},
            )
            assert r.status_code == 422, r.status_code
            assert "incorrect" in r.text

            # Mismatched new/confirm → 422.
            r = rotator.post(
                "/web/account/password",
                data={"current_password": "starter", "new_password": "newpass",
                      "confirm_password": "oops", "_csrf": csrf_p},
            )
            assert r.status_code == 422 and "do not match" in r.text

            # Correct submission → success banner.
            r = rotator.post(
                "/web/account/password",
                data={"current_password": "starter", "new_password": "newpass1",
                      "confirm_password": "newpass1", "_csrf": csrf_p},
            )
            assert r.status_code == 200, (r.status_code, r.text)
            assert "Password updated" in r.text

            # Old password no longer works.
            app.state.login_attempts.clear()
            re_auth = TestClient(app, follow_redirects=False)
            re_auth.get("/login")
            r = re_auth.post("/login", data={
                "login": "rotator", "password": "starter",
                "_csrf": re_auth.cookies.get("pyvelm_csrf") or "",
            })
            assert r.status_code == 401, r.status_code
            # New password works.
            r = re_auth.post("/login", data={
                "login": "rotator", "password": "newpass1",
                "_csrf": re_auth.cookies.get("pyvelm_csrf") or "",
            })
            assert r.status_code == 303, (r.status_code, r.text)
            app.state.login_attempts.clear()
            print("password change: bcrypt verify + rotate + old password retired")

            # POST /login with bad credentials returns 401 + error msg.
            r = anon2.post(
                "/login",
                data={"login": "admin", "password": "WRONG", "next": "/",
                      "_csrf": csrf_tok},
            )
            assert r.status_code == 401, r.status_code
            assert "Invalid username or password" in r.text
            print("POST /login bad creds: 401 with error message")

            # POST /login with correct credentials: 303 redirect + cookie.
            r = anon2.post(
                "/login",
                data={"login": "admin", "password": "admin", "next": "/",
                      "_csrf": csrf_tok},
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
            # CSRF: send the token via header since /logout has no form.
            r = cookie_client.post(
                "/logout",
                headers={"X-CSRF-Token": cookie_client.cookies.get("pyvelm_csrf") or ""},
            )
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
                headers={
                    "HX-Request": "true",
                    "X-CSRF-Token": stale_client.cookies.get("pyvelm_csrf") or "",
                },
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

            # O2m table widget: the currency form embeds a table of
            # res.currency.rate rows. USD has at least one seeded rate;
            # the parent form must render a <table> and an "Add" link
            # carrying the currency_id back into the rate form's /new.
            with pool.connection() as ccy_conn:
                from pyvelm import Environment as _EnvCcy
                ccy_env = _EnvCcy(ccy_conn, registry=reg, uid=1)
                usd = ccy_env["res.currency"].search(
                    [("code", "=", "USD")], limit=1,
                )
                assert usd, "USD must be seeded"
                usd_id = usd.id
            r = client.get(f"/web/views/admin/currency.form/record/{usd_id}")
            assert r.status_code == 200, r.text
            body = r.text
            assert "Exchange rates" in body, "rates section missing"
            assert "<table" in body, "o2m table widget did not emit a <table>"
            expected_add = (
                f'/web/views/admin/currency.rate.form/new?currency_id={usd_id}'
            )
            assert expected_add in body, (
                "Add link missing or prefill absent: "
                f"expected {expected_add!r} in form HTML"
            )
            # The /new endpoint must honor the prefill and render the
            # parent as the Many2one's selected value.
            r_new = client.get(expected_add)
            assert r_new.status_code == 200, r_new.text
            # Many2one display falls back to `name` — "US Dollar" for USD.
            assert "US Dollar" in r_new.text, (
                "prefilled currency_id label not shown"
            )
            print("o2m table: currency form lists rates + Add prefills currency_id OK")

            # Slice 2C: edit-mode O2m table is editable.
            # GET the /edit page and check the widget emitted inline
            # inputs, a template row, and the Add-row button.
            r_edit = client.get(
                f"/web/views/admin/currency.form/record/{usd_id}/edit"
            )
            assert r_edit.status_code == 200, r_edit.text
            edit_body = r_edit.text
            assert "data-pv-o2m-root" in edit_body, "o2m root marker missing"
            assert "data-pv-o2m-template" in edit_body, "template row missing"
            assert "data-pv-o2m-add" in edit_body, "Add-row button missing"
            assert 'name="rate_ids[0][_op]"' in edit_body, (
                "namespaced o2m _op input missing"
            )
            assert 'value="update"' in edit_body, (
                "existing rows should be flagged op=update"
            )

            # POST a parent save that performs all three commands in
            # one transaction: update the existing rate, create a new
            # one, and delete an arbitrary other rate. Then verify by
            # reading the rates back.
            with pool.connection() as ccy_conn2:
                from pyvelm import Environment as _EnvCcy2
                ccy_env2 = _EnvCcy2(ccy_conn2, registry=reg, uid=1)
                usd_rec = ccy_env2["res.currency"].browse(usd_id)
                rate_rows = list(usd_rec.rate_ids)
                assert rate_rows, "USD must have at least one rate"
                target_rate = rate_rows[0]
                target_rate_id = target_rate.id

                # Pick a delete target on a *different* currency so
                # this test doesn't fight the rest of the suite.
                other_ccy = ccy_env2["res.currency"].search(
                    [("code", "=", "GBP")], limit=1,
                )
                assert other_ccy, "GBP must be seeded"
                # GBP shares the same form, so post a separate save
                # against GBP that deletes its first rate.
                gbp_id = other_ccy.id
                gbp_rate = list(other_ccy.rate_ids)[0]
                gbp_rate_id = gbp_rate.id

            # Update existing USD rate + add a new one in one save.
            from datetime import datetime as _dt_e, timedelta as _td_e
            new_date = (_dt_e.utcnow() - _td_e(days=2)).strftime(
                "%Y-%m-%dT%H:%M"
            )
            old_date = (_dt_e.utcnow() - _td_e(days=10)).strftime(
                "%Y-%m-%dT%H:%M"
            )
            r_save = client.post(
                f"/web/views/admin/currency.form/record/{usd_id}",
                data={
                    "code": "USD",
                    "name": "US Dollar",
                    "symbol": "$",
                    "rounding": "0.01",
                    "active": "on",
                    "rate_ids[0][_op]": "update",
                    "rate_ids[0][id]": str(target_rate_id),
                    "rate_ids[0][currency_id]": str(usd_id),
                    "rate_ids[0][date]": old_date,
                    "rate_ids[0][rate]": "1.00",
                    "rate_ids[1][_op]": "create",
                    "rate_ids[1][currency_id]": str(usd_id),
                    "rate_ids[1][date]": new_date,
                    "rate_ids[1][rate]": "1.05",
                },
            )
            assert r_save.status_code == 200, (r_save.status_code, r_save.text)

            # Delete the GBP rate via the same nested-form mechanism.
            r_del = client.post(
                f"/web/views/admin/currency.form/record/{gbp_id}",
                data={
                    "code": "GBP",
                    "name": "Pound Sterling",
                    "symbol": "£",
                    "rounding": "0.01",
                    "active": "on",
                    "rate_ids[0][_op]": "delete",
                    "rate_ids[0][id]": str(gbp_rate_id),
                },
            )
            assert r_del.status_code == 200, (r_del.status_code, r_del.text)

            # Verify: USD now has a fresh rate row at the new date,
            # the original row's rate is 1.00, and the GBP rate is gone.
            with pool.connection() as ccy_conn3:
                from pyvelm import Environment as _EnvCcy3
                ccy_env3 = _EnvCcy3(ccy_conn3, registry=reg, uid=1)
                Rate = ccy_env3["res.currency.rate"]
                updated = Rate.browse(target_rate_id)
                assert abs(updated.rate - 1.00) < 1e-9, updated.rate
                fresh = Rate.search(
                    [("currency_id", "=", usd_id),
                     ("rate", "=", 1.05)], limit=1,
                )
                assert fresh, "create-via-parent-form did not persist"
                deleted = Rate.search([("id", "=", gbp_rate_id)])
                assert not deleted, "delete-via-parent-form did not unlink"
            print("o2m inline edit: create + update + delete commit via parent save OK")

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

                # pyvelm.cli._tick mirrors what the background runner
                # calls on every loop iteration: open a connection from
                # a pool, wrap it in an env, run_due against the live
                # registry. Confirms the CLI wrapper hands the right
                # shape to CronJob even though the loop itself can't
                # be unit-tested without spawning a subprocess.
                from pyvelm import cli as _cli
                past = _dt.utcnow() - _td(seconds=1)
                with wf_env.transaction():
                    cron.write({"nextcall": past})
                wf_env.cache.invalidate(model_name="ir.cron", ids=[cron.id])
                _cli._tick(pool, reg)
                with pool.connection() as side_conn:
                    rows = side_conn.execute(
                        "SELECT nextcall FROM ir_cron WHERE id = %s",
                        [cron.id],
                    ).fetchone()
                assert rows is not None and rows[0] > _dt.utcnow(), rows
                print("cron CLI: _tick advances nextcall via the pool path")

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

                # ----- Slice 2 hardening: outgoing-mail dispatcher -----
                # Queue an outgoing message + a doomed one, then drain
                # the queue with a captured ConsoleBackend so we can
                # see exactly what would have been sent.
                from pyvelm.mail import Message as MailMessage
                queued = wf_env["mail.message"].create({
                    "model": "res.partner",
                    "res_id": alice.id,
                    "body": "Welcome to pyvelm.",
                    "subject": "Hello",
                    "recipient_email": "alice@example.test",
                    "state": "outgoing",
                })
                doomed = wf_env["mail.message"].create({
                    "model": "res.partner",
                    "res_id": alice.id,
                    "body": "This one will explode.",
                    "subject": "Boom",
                    "recipient_email": "boom@example.test",
                    "state": "outgoing",
                })

                class _Capture:
                    """Minimal backend collecting sent calls; one entry
                    explodes so we exercise the failure branch."""
                    def __init__(self) -> None:
                        self.sent: list[dict] = []
                    def send(self, *, to, subject, body, from_addr=None):
                        if to == "boom@example.test":
                            raise RuntimeError("server hung up")
                        self.sent.append({"to": to, "subject": subject,
                                          "body": body, "from_addr": from_addr})

                cap = _Capture()
                result = MailMessage.dispatch_outgoing(wf_env, backend=cap)
                assert result == {"sent": 1, "failed": 1}, result
                assert cap.sent == [{
                    "to": "alice@example.test", "subject": "Hello",
                    "body": "Welcome to pyvelm.", "from_addr": None,
                }], cap.sent

                # Re-read so the state transitions are visible. Both
                # rows should have left the "outgoing" queue, one with
                # error context.
                wf_env.cache.invalidate(model_name="mail.message",
                                         ids=[queued.id, doomed.id])
                queued_row = wf_env["mail.message"].browse(queued.id)
                doomed_row = wf_env["mail.message"].browse(doomed.id)
                assert queued_row.state == "sent"
                assert doomed_row.state == "failed"
                assert doomed_row.error and "hung up" in doomed_row.error

                # A second dispatch is a no-op — nothing's outgoing.
                again = MailMessage.dispatch_outgoing(wf_env, backend=cap)
                assert again == {"sent": 0, "failed": 0}, again
                print("mail dispatcher: sent → sent, failed → failed + error captured")

                # And the base/hooks seed actually landed: the cron +
                # action exist with the expected names so the bg
                # runner will fire dispatch_outgoing every minute.
                cron_row = wf_env["ir.cron"].search(
                    [("name", "=", "Mail dispatcher")], limit=1,
                )
                assert cron_row, "Mail dispatcher cron not seeded"
                assert cron_row.action_id.name == "Mail dispatcher"
                print("mail dispatcher: cron + action seeded by base hook")

                # ----- Currencies (Slice A of Stage 11) -----
                # Fresh install seeded USD / EUR / GBP / JPY with
                # opening rates; verify the convert helper picks the
                # right rate for the requested date.
                from datetime import datetime as _dt, timedelta as _td
                Currency = wf_env["res.currency"]
                Rate = wf_env["res.currency.rate"]
                seeded = {c.code: c for c in Currency.search([])}
                assert {"USD", "EUR", "GBP", "JPY"} <= set(seeded), seeded
                assert seeded["JPY"].rounding == 1.0
                assert seeded["USD"].rounding == 0.01

                # Same-currency convert is a passthrough.
                assert seeded["USD"].convert(100.0, seeded["USD"]) == 100.0

                # Normalize the rate histories — earlier runs of this
                # script (and the o2m editing test upstream) may have
                # appended rows. Wipe USD/EUR/JPY back to a known
                # single-row state so the math is deterministic.
                with wf_env.transaction():
                    for code, rate in (("USD", 1.00), ("EUR", 0.92),
                                       ("JPY", 149.5)):
                        old = Rate.search([("currency_id", "=", seeded[code].id)])
                        if old:
                            old.unlink()
                        Rate.create({
                            "currency_id": seeded[code].id,
                            "date": _dt.utcnow() - _td(days=1),
                            "rate": rate,
                        })
                wf_env.cache.invalidate(model_name="res.currency.rate")

                # 100 USD → EUR uses the 0.92 rate.
                eur = seeded["USD"].convert(100.0, seeded["EUR"])
                assert abs(eur - 92.0) < 1e-9, eur

                # 100 EUR → JPY rides USD as the implicit reference:
                # 100 / 0.92 * 149.5
                jpy = seeded["EUR"].convert(100.0, seeded["JPY"])
                assert abs(jpy - (100.0 / 0.92 * 149.5)) < 1e-6, jpy

                # Adding a newer rate shifts the conversion result.
                with wf_env.transaction():
                    Rate.create({
                        "currency_id": seeded["EUR"].id,
                        "date": _dt.utcnow(),
                        "rate": 0.85,
                    })
                import time as _time
                _time.sleep(0.05)
                wf_env.cache.invalidate(model_name="res.currency.rate")
                eur2 = seeded["USD"].convert(100.0, seeded["EUR"])
                assert abs(eur2 - 85.0) < 1e-9, eur2

                # No rate covering an early historical date → raises.
                long_ago = _dt(2000, 1, 1)
                try:
                    seeded["USD"].convert(100.0, seeded["EUR"], date=long_ago)
                except ValueError:
                    pass
                else:
                    raise AssertionError(
                        "convert() should raise when no rate covers the date"
                    )
                print("currencies: seed, convert, dated rates, no-rate error OK")

                # ----- Monetary field (Slice C of Stage 11) -----
                # The field type itself, with rounding helper + widget
                # registration. Lighter-touch than spinning up a full
                # model with a Monetary column: this is what apps need
                # to know about the API.
                from pyvelm import Monetary
                from pyvelm.fields import Float as _Float
                from pyvelm.render import find_renderer
                # Subclassing keeps Float's SQL type + python_type.
                assert issubclass(Monetary, _Float)
                m = Monetary(currency_field="company_currency_id")
                assert m.currency_field == "company_currency_id"
                # Defaults to "currency_id" — the convention slice B set up.
                assert Monetary().currency_field == "currency_id"
                # Rounding honors the currency's `rounding` step.
                assert Monetary.round_with(12.345, seeded["USD"]) == 12.35
                assert Monetary.round_with(149.7, seeded["JPY"]) == 150.0
                assert Monetary.round_with(None, seeded["USD"]) is None
                # No currency → passthrough.
                assert Monetary.round_with(12.345, None) == 12.345
                # Widget is registered for both display and edit modes.
                disp = find_renderer(m, hint=None, mode="display")
                edit = find_renderer(m, hint=None, mode="edit")
                assert disp.__name__ == "_render_monetary", disp
                assert edit.__name__ == "_edit_monetary", edit
                print("Monetary: subclass, round_with, widgets registered OK")
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

                # Slice B of Stage 11 — install + migration must give
                # the seeded company a currency_id (USD by default).
                assert my_company.currency_id, "company must have a currency_id"
                assert my_company.currency_id.code == "USD", my_company.currency_id.code
                print(f"company currency: {my_company.name!r} → {my_company.currency_id.code} OK")

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
