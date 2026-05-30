"""Minimal full-stack HTTP smoke (install + TestClient).

Exercises ``web.py`` / ``render.py`` without the full ``examples/basic.py``
script. Runs when ``PYVELM_DSN_TEST`` is set (CI provides Postgres or SQLite).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.render import install_module_action
from pyvelm.tests.support.db import install_modules, open_database, reset_database
from pyvelm.web import create_app

_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "modules"
_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [_EXAMPLE_ROOT]
_MINIMAL_MODULES = {"base", "admin", "partners"}


@pytest.mark.integration
def test_http_smoke_login_list_api(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)

    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg)
        specs = install_modules(env, _MODULE_ROOTS)
        install_module_action(env, _MODULE_ROOTS, "partners")
        installed = {s.name for s in specs} | {"partners"}
        assert _MINIMAL_MODULES <= installed

        Partner = env["res.partner"]
        france = env["res.country"].create({"name": "France", "code": "FR"})
        Partner.create({"name": "Smoke Alice", "code": "SMA", "country_id": france})
        france_id = france.id

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        client.auth = ("admin", "admin")

        login = client.get("/login", follow_redirects=False)
        assert login.status_code in (200, 302)

        shell = client.get("/web/admin")
        assert shell.status_code == 200
        assert "Dashboard" in shell.text or "Partners" in shell.text

        partners = client.get("/web/views/partners/partner.list")
        assert partners.status_code == 200
        assert "Smoke Alice" in partners.text

        alice_row = client.get(
            "/api/records",
            params={
                "model": "res.partner",
                "domain": '[["name","=","Smoke Alice"]]',
                "fields": "id",
            },
        ).json()["records"][0]
        form = client.get(
            f"/web/views/partners/partner.form/record/{alice_row['id']}"
        )
        assert form.status_code == 200
        assert "Smoke Alice" in form.text

        frag = client.get(
            "/web/records/partners/partner.list",
            params={"page": 1, "page_size": 10},
        )
        assert frag.status_code == 200
        assert "<tr" in frag.text

        listing = client.get(
            "/api/records",
            params={"model": "res.partner", "fields": "name,code"},
        )
        assert listing.status_code == 200
        names = {r["name"] for r in listing.json()["records"]}
        assert "Smoke Alice" in names

        created = client.post(
            "/api/records",
            params={"model": "res.partner"},
            json={"name": "Smoke Bob", "code": "SMB", "country_id": france_id},
        )
        assert created.status_code == 201
        assert created.json()["name"] == "Smoke Bob"

        apps = client.get("/web/apps")
        assert apps.status_code == 200
        assert "partners" in apps.text.lower()

        static = client.get("/web/static/pyvelm.css")
        assert static.status_code == 200

    db.dispose()
