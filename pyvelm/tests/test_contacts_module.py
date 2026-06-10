"""Smoke tests for the bundled contacts module."""
from __future__ import annotations

from pathlib import Path

import pytest

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.loader import BOOTSTRAP_MODULES
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database


@pytest.mark.integration
def test_contacts_is_bootstrap_module():
    assert "contacts" in BOOTSTRAP_MODULES


@pytest.mark.integration
def test_contacts_installs_res_partner(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["contacts"], list(BUILTIN_MODULE_ROOTS))

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        assert "res.partner" in env.registry
        assert env.registry._model_module["res.partner"] == "contacts"
        partner = env["res.partner"].create({
            "name": "Acme Corp",
            "code": "ACM-1",
        })
        assert partner.display_name.startswith("Acme Corp")
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_partners_example_extends_contacts(pyvelm_dsn: str):
    examples = Path(__file__).resolve().parents[2] / "examples" / "modules"
    roots = list(BUILTIN_MODULE_ROOTS) + [examples]
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "contacts", "partners"], roots)

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        assert "age" in env.registry["res.partner"]._fields
        assert "tag_ids" in env.registry["res.partner"]._fields
        assert env.registry._model_module["res.partner"] == "contacts"
    finally:
        conn.close()
        db.dispose()
