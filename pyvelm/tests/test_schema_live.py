"""HTTP integration for Filament-style form ``live()`` re-renders."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database
from pyvelm.web import create_app

_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "modules"
_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [_EXAMPLE_ROOT]


def _login(client: TestClient) -> None:
    client.get("/login")
    csrf = client.cookies.get("pyvelm_csrf")
    resp = client.post(
        "/login",
        data={"login": "admin", "password": "admin", "_csrf": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def _csrf(client: TestClient) -> str:
    token = client.cookies.get("pyvelm_csrf")
    assert token
    return token


@pytest.mark.integration
def test_form_live_visibility_on_new_partner(pyvelm_dsn: str):
    """``visible_when`` predicates re-evaluate via the live HTMX endpoint."""
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "partners"], _MODULE_ROOTS)

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        _login(client)
        new_form = client.get("/web/views/partners/partner.form/new")
        assert new_form.status_code == 200

        minor = client.post(
            "/web/views/partners/partner.form/live?driver=age",
            data={
                "name": "Minor",
                "code": "MIN-1",
                "age": "10",
                "_csrf": _csrf(client),
            },
        )
        assert minor.status_code == 200
        assert 'data-field="birth_date"' not in minor.text

        adult = client.post(
            "/web/views/partners/partner.form/live?driver=age",
            data={
                "name": "Adult",
                "code": "ADU-1",
                "age": "25",
                "_csrf": _csrf(client),
            },
        )
        assert adult.status_code == 200
        assert 'data-field="birth_date"' in adult.text
        assert "/web/views/partners/partner.form/live?driver=age" in adult.text

        no_phone = client.post(
            "/web/views/partners/partner.form/live?driver=email",
            data={
                "name": "No Mail",
                "code": "NML-1",
                "email": "",
                "_csrf": _csrf(client),
            },
        )
        assert no_phone.status_code == 200
        assert 'data-field="phone"' not in no_phone.text

        with_phone = client.post(
            "/web/views/partners/partner.form/live?driver=email",
            data={
                "name": "With Mail",
                "code": "WML-1",
                "email": "user@example.com",
                "_csrf": _csrf(client),
            },
        )
        assert with_phone.status_code == 200
        assert 'data-field="phone"' in with_phone.text

    db.dispose()


@pytest.mark.integration
def test_form_live_visibility_on_edit_partner(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "partners"], _MODULE_ROOTS)
        admin = env["res.users"].browse([1])
        admin.ensure_one()
        company_id = admin.company_id.id if admin.company_id else None
        partner = env["res.partner"].create(
            {
                "name": "Live Edit",
                "code": "LIV-1",
                "age": 30,
                "company_id": company_id,
            }
        )
        partner_id = partner.id

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        _login(client)
        resp = client.post(
            f"/web/views/partners/partner.form/record/{partner_id}/live?driver=age",
            data={
                "name": "Live Edit",
                "code": "LIV-1",
                "age": "12",
                "_csrf": _csrf(client),
            },
        )
        assert resp.status_code == 200
        assert 'data-field="birth_date"' not in resp.text

    db.dispose()


@pytest.mark.integration
def test_form_live_requires_auth(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "partners"], _MODULE_ROOTS)

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app, follow_redirects=False) as client:
        resp = client.post(
            "/web/views/partners/partner.form/live?driver=age",
            data={"name": "X", "code": "X"},
        )
        assert resp.status_code == 302
        assert "/login" in (resp.headers.get("location") or "")

    db.dispose()
