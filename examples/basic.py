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
