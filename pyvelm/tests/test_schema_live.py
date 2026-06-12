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


def _live_post(client: TestClient, url: str, data: dict):
    """POST a live re-render; return the HTMX body fragment (not a login redirect)."""
    resp = client.post(
        url,
        data=data,
        follow_redirects=False,
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200, resp.text[:500]
    assert "<!DOCTYPE" not in resp.text
    return resp


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
        client.auth = ("admin", "admin")
        live_url = "/web/views/partners/partner.form/live?driver=age"

        minor = _live_post(
            client,
            live_url,
            {"name": "Minor", "code": "MIN-1", "age": "10"},
        )
        assert 'data-field="birth_date"' not in minor.text

        adult = _live_post(
            client,
            live_url,
            {"name": "Adult", "code": "ADU-1", "age": "25"},
        )
        assert 'data-field="birth_date"' in adult.text
        assert live_url in adult.text

        email_url = "/web/views/partners/partner.form/live?driver=email"
        no_phone = _live_post(
            client,
            email_url,
            {"name": "No Mail", "code": "NML-1", "email": ""},
        )
        assert 'data-field="phone"' not in no_phone.text

        with_phone = _live_post(
            client,
            email_url,
            {"name": "With Mail", "code": "WML-1", "email": "user@example.com"},
        )
        assert 'data-field="phone"' in with_phone.text
        assert "aria-hidden=\"true\">*</span>" in with_phone.text

        # ``email`` has no explicit ``live()`` but is an inferred driver.
        inferred = _live_post(
            client,
            "/web/views/partners/partner.form/live?driver=email",
            {"name": "Infer", "code": "INF-1", "email": "a@b.c"},
        )
        assert "hx-post=" in inferred.text
        assert "driver=email" in inferred.text

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
        client.auth = ("admin", "admin")
        resp = _live_post(
            client,
            f"/web/views/partners/partner.form/record/{partner_id}/live?driver=age",
            {"name": "Live Edit", "code": "LIV-1", "age": "12"},
        )
        assert 'data-field="birth_date"' not in resp.text

    db.dispose()


@pytest.mark.integration
def test_form_live_required_and_readonly_crm(pyvelm_dsn: str):
    """``required_when`` / ``readonly_when`` update on stage ``live()`` re-render."""
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "partners", "crm"], _MODULE_ROOTS)

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        client.auth = ("admin", "admin")
        live_url = "/web/views/crm/lead.form/live?driver=stage"

        lost = _live_post(
            client,
            live_url,
            {"name": "Lost deal", "stage": "lost", "expected_revenue": "100"},
        )
        assert 'data-field="expected_revenue"' in lost.text
        assert "readonly" in lost.text.lower() or 'readonly="readonly"' in lost.text

        early = _live_post(
            client,
            live_url,
            {"name": "Early", "stage": "new"},
        )
        assert 'data-field="probability"' not in early.text

        won = _live_post(
            client,
            live_url,
            {"name": "Won deal", "stage": "won"},
        )
        assert 'data-field="probability"' in won.text
        prob_cell = won.text.split('data-field="probability"')[1][:800]
        assert "aria-hidden=\"true\">*</span>" in prob_cell

    db.dispose()


@pytest.mark.integration
def test_form_live_parent_domain_on_partner(pyvelm_dsn: str):
    """``options_domain`` is baked into the parent_id M2O search URL."""
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

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        client.auth = ("admin", "admin")
        resp = _live_post(
            client,
            "/web/views/partners/partner.form/live?driver=company_id",
            {
                "name": "Scoped",
                "code": "SCP-1",
                "company_id": str(company_id) if company_id else "",
            },
        )
        assert 'data-field="parent_id"' in resp.text
        chunk = resp.text.split('data-field="parent_id"')[1][:2500]
        assert "domain=" in chunk
        if company_id:
            assert str(company_id) in chunk

    db.dispose()


@pytest.mark.integration
def test_m2o_search_respects_domain_param(pyvelm_dsn: str):
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
        env["res.partner"].create(
            {"name": "Same Co", "code": "SMC-1", "company_id": company_id}
        )
        env["res.partner"].create({"name": "Other Co", "code": "OTH-1", "company_id": None})

    app = create_app(reg, db, module_roots=_MODULE_ROOTS)
    with TestClient(app) as client:
        client.auth = ("admin", "admin")
        import json
        from urllib.parse import quote

        if company_id:
            domain = quote(json.dumps([["company_id", "=", company_id]]))
            resp = client.get(
                f"/api/m2o/search?model=res.partner&domain={domain}&limit=50"
            )
            assert resp.status_code == 200
            labels = [r["label"] for r in resp.json()["results"]]
            assert "Same Co" in labels
            assert "Other Co" not in labels

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
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 204
        assert "/login" in (resp.headers.get("HX-Redirect") or "")

    db.dispose()
