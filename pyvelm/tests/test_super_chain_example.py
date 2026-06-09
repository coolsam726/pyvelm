"""Integration tests for the super_chain_demo example modules.

Exercises Odoo-style ``super().button_cancel()`` across three stacked
``_inherit`` extensions loaded through the real module loader.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database

_EXAMPLE_ROOTS = list(BUILTIN_MODULE_ROOTS) + [
    Path(__file__).resolve().parents[2] / "examples" / "modules"
]

_SUPER_CHAIN_MODULES = [
    "admin",
    "super_chain_demo",
    "super_chain_demo_a",
    "super_chain_demo_b",
]


@pytest.fixture
def super_chain_env(pyvelm_dsn):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, _SUPER_CHAIN_MODULES, _EXAMPLE_ROOTS)
    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        yield env
    finally:
        conn.close()
        db.dispose()


def test_inherit_chain_loaded_in_order(super_chain_env):
    env = super_chain_env
    chain = env.registry.inherit_chain("super_chain.order")
    names = [cls.__name__ for cls in chain]
    assert names == ["DemoOrder", "DemoOrderExtA", "DemoOrderExtB"]
    assert env.registry["super_chain.order"].__name__ == "DemoOrderExtB"


def test_button_cancel_super_chain(super_chain_env):
    """Odoo-style override: ``res = super().button_cancel()`` stacks correctly."""
    env = super_chain_env
    Order = env["super_chain.order"]

    with env.transaction():
        order = Order.create({"name": "SO001"})

    assert order.state == "draft"

    res = order.button_cancel()

    assert res["state"] == "cancelled"
    assert res["layers"] == ["base", "ext_a", "ext_b"]

    env.cache.invalidate(model_name="super_chain.order", ids=[order.id])
    assert order.state == "cancelled"
    assert order.cancel_note == "cancelled via ext_a"


def test_middle_extension_can_skip_override(super_chain_env):
    """Extension without ``button_cancel`` still delegates through MRO."""
    env = super_chain_env
    reg = env.registry

    # Simulate a fourth module that adds a field but no button override.
    with reg.activate():
        from pyvelm import Char, models

        class DemoOrderExtC(models.Model):
            _inherit = "super_chain.order"
            extra = Char()

    Order = env["super_chain.order"]
    with env.transaction():
        order = Order.create({"name": "SO002"})

    res = order.button_cancel()
    assert res["layers"] == ["base", "ext_a", "ext_b"]
