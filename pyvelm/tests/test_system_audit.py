"""Tests for the bundled ``system_audit`` module."""
from __future__ import annotations

from datetime import timedelta

import pytest

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.loader import BOOTSTRAP_MODULES
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database
from pyvelm.timestamps import utc_now


@pytest.mark.integration
def test_system_audit_is_opt_in_module():
    assert "system_audit" not in BOOTSTRAP_MODULES


@pytest.mark.integration
def test_system_audit_install_registers_models(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(
            env,
            ["admin", "system_audit"],
            list(BUILTIN_MODULE_ROOTS),
        )

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        for model in (
            "ir.audit.log",
            "ir.login.log",
            "ir.user.lifecycle",
        ):
            assert model in env.registry
        cron = env["ir.cron"].search([("name", "=", "Audit log retention")], limit=1)
        assert cron
        action = cron.action_id
        assert action.action_type == "audit_purge"
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_crud_audit_log_on_partner_create(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(
            env,
            ["admin", "contacts", "system_audit"],
            list(BUILTIN_MODULE_ROOTS),
        )

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        partner = env["res.partner"].create({"name": "Audit Me", "code": "AUD-1"})
        logs = env["ir.audit.log"].search(
            [("model", "=", "res.partner"), ("res_id", "=", partner.id)]
        )
        assert logs
        logs.ensure_one()
        assert logs.action == "create"
        assert "Audit Me" in (logs.new_values or "")
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_audit_models_do_not_self_log(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "system_audit"], list(BUILTIN_MODULE_ROOTS))

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    try:
        before = env["ir.audit.log"].search_count([])
        env.sudo()["ir.audit.log"].create(
            {
                "name": "manual",
                "model": "res.partner",
                "res_id": 1,
                "action": "create",
            }
        )
        after = env["ir.audit.log"].search_count([])
        assert after == before + 1
        self_logs = env["ir.audit.log"].search([("model", "=", "ir.audit.log")])
        assert not self_logs
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_retention_purge_deletes_old_rows(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "system_audit"], list(BUILTIN_MODULE_ROOTS))

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        stale = env.sudo()["ir.audit.log"].create(
            {
                "name": "old row",
                "model": "res.partner",
                "res_id": 1,
                "action": "write",
            }
        )
        fresh = env.sudo()["ir.audit.log"].create(
            {
                "name": "fresh row",
                "model": "res.partner",
                "res_id": 2,
                "action": "write",
            }
        )
        stale_id = stale.ids[0]
        fresh_id = fresh.ids[0]
        old_ts = utc_now() - timedelta(days=120)
        env.conn.execute(
            'UPDATE "ir_audit_log" SET "created_at" = %s WHERE "id" = %s',
            [old_ts, stale_id],
        )
        from system_audit.retention import purge_audit_logs

        deleted = purge_audit_logs(env)
        assert deleted >= 1
        assert not env["ir.audit.log"].search([("id", "=", stale_id)])
        assert env["ir.audit.log"].search([("id", "=", fresh_id)])
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_partner_write_and_unlink_audit(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(
            env,
            ["admin", "contacts", "system_audit"],
            list(BUILTIN_MODULE_ROOTS),
        )

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        partner = env["res.partner"].create({"name": "Trace", "code": "TRC"})
        partner_id = partner.ids[0]
        partner.write({"name": "Trace Updated"})
        write_logs = env["ir.audit.log"].search(
            [
                ("model", "=", "res.partner"),
                ("res_id", "=", partner_id),
                ("action", "=", "write"),
            ]
        )
        assert write_logs
        partner.unlink()
        unlink_logs = env["ir.audit.log"].search(
            [
                ("model", "=", "res.partner"),
                ("res_id", "=", partner_id),
                ("action", "=", "unlink"),
            ]
        )
        assert unlink_logs
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_user_lifecycle_events(pyvelm_dsn: str):
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "system_audit"], list(BUILTIN_MODULE_ROOTS))

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        user = env.sudo()["res.users"].create(
            {
                "name": "Audit User",
                "login": "audit.user@example.com",
                "password": "secret",
                "active": True,
            }
        )
        created = env["ir.user.lifecycle"].search(
            [("user_id", "=", user.id), ("event", "=", "created")]
        )
        assert created
        user.write({"active": False})
        deactivated = env["ir.user.lifecycle"].search(
            [("user_id", "=", user.id), ("event", "=", "deactivated")]
        )
        assert deactivated
    finally:
        conn.close()
        db.dispose()


def test_login_logger_unit():
    from unittest.mock import MagicMock

    from system_audit.login import log_login_event

    env = MagicMock()
    env.registry = {}
    log_login_event(env, event="login_failure", email="x@y.z")

    created: list[dict] = []
    model = MagicMock()
    model.create.side_effect = lambda vals: created.append(vals)
    env.registry = {"ir.login.log": object()}
    sudo_env = MagicMock()
    sudo_env.__getitem__.return_value = model
    env.sudo.return_value = sudo_env
    env.context = {}
    log_login_event(env, event="login_success", email="a@b.c", user_id=7)
    assert created[0]["event"] == "login_success"
    assert created[0]["user_id"] == 7


def test_retention_days_invalid_env(monkeypatch):
    from system_audit.retention import retention_days

    monkeypatch.setenv("PYVELM_AUDIT_RETENTION_DAYS", "not-a-number")
    assert retention_days() == 90


def test_retention_days_custom(monkeypatch):
    from system_audit.retention import retention_days

    monkeypatch.setenv("PYVELM_AUDIT_RETENTION_DAYS", "30")
    assert retention_days() == 30


def test_manifest_bootstrap_false():
    from pyvelm.manifest import Manifest

    data = Manifest.make("audit").version(0, 1, 0).bootstrap(False).to_dict()
    assert data["BOOTSTRAP"] is False


def test_lifecycle_track_create():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import track_create

    events: list[str] = []
    import system_audit.lifecycle as lifecycle_mod

    lifecycle_mod.log_event = lambda _e, _u, event, detail=None: events.append(event)  # type: ignore[assignment]
    track_create(MagicMock(), 4, {"name": "Ann", "email": "a@b.c"})
    assert events == ["created"]


def test_lifecycle_password_and_groups_events():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import track_write

    created: list[tuple] = []

    def _log(env, user_id, event, detail=None):
        created.append((event, detail))

    import system_audit.lifecycle as lifecycle_mod

    lifecycle_mod.log_event = _log  # type: ignore[assignment]
    track_write(
        MagicMock(),
        9,
        {"password": "x", "group_ids": [1, 2]},
        {"group_ids": [1]},
    )
    assert ("password_changed", None) in [(e, d) for e, d in created]
    assert any(e == "groups_changed" for e, _ in created)


def test_logger_company_resolution_for_res_company():
    from unittest.mock import MagicMock

    from system_audit.logger import log_crud

    created: list[dict] = []
    model = MagicMock()
    model.create.side_effect = lambda vals: created.append(vals)
    sudo = MagicMock()
    sudo.__getitem__.return_value = model
    env = MagicMock()
    env.registry = {"ir.audit.log": object()}
    env.uid = 1
    env.company_id = 99
    env.context = {}
    env.with_company.return_value = env
    env.sudo.return_value = sudo
    log_crud(env, "res.company", 12, "write", old_values={}, new_values={})
    assert created[0]["company_id"] == 12


def test_purge_skips_missing_models():
    from unittest.mock import MagicMock

    from system_audit.retention import purge_audit_logs

    env = MagicMock()
    env.registry = {"ir.audit.log": object()}
    env.sudo.return_value = env
    env.__getitem__.return_value.search.return_value = MagicMock(_ids=())
    assert purge_audit_logs(env) == 0


def test_is_audit_model():
    from system_audit.logger import is_audit_model

    assert is_audit_model("ir.audit.log")
    assert not is_audit_model("res.partner")


def test_request_context_reads_env_context():
    from unittest.mock import MagicMock

    from pyvelm.env import Environment
    from system_audit.context import request_context

    env = Environment(MagicMock(), registry=MagicMock(), uid=1)
    env = env.with_context(
        audit_ip="10.0.0.1",
        audit_user_agent="pytest",
        audit_session_id="sess",
        audit_session_lifetime_minutes=15,
    )
    ctx = request_context(env)
    assert ctx["ip"] == "10.0.0.1"
    assert ctx["user_agent"] == "pytest"
    assert ctx["session_id"] == "sess"
    assert ctx["session_lifetime_minutes"] == 15


def test_seed_retention_cron_noop_without_registry():
    from unittest.mock import MagicMock

    from system_audit.hooks import _seed_retention_cron

    env = MagicMock()
    env.registry = {}
    _seed_retention_cron(env)

    env.registry = {"ir.cron": object()}
    _seed_retention_cron(env)


def test_seed_retention_cron_skips_when_job_exists():
    from unittest.mock import MagicMock

    from system_audit.hooks import _seed_retention_cron

    cron = MagicMock()
    cron.search.return_value = MagicMock(__bool__=lambda _s: True)
    action = MagicMock()
    env = MagicMock()
    env.registry = {"ir.cron": object(), "ir.actions.server": object()}

    def _getitem(name):
        return cron if name == "ir.cron" else action

    env.__getitem__.side_effect = _getitem
    _seed_retention_cron(env)
    cron.create.assert_not_called()


def test_fire_on_create_skips_audit_models():
    from unittest.mock import MagicMock, patch

    from system_audit.listener import fire_on_create

    env = MagicMock()
    env.registry = {"ir.audit.log": object()}
    record = MagicMock()
    record._name = "ir.audit.log"
    with patch("system_audit.listener.log_crud") as log_crud:
        fire_on_create(env, record, {"name": "x"})
        log_crud.assert_not_called()


def test_serialize_value_handles_field_types():
    from unittest.mock import MagicMock

    from pyvelm.fields import Boolean, Char, Many2many, Many2one
    from system_audit.listener import _serialize_value

    assert _serialize_value(Boolean.bare(), False) is None
    assert _serialize_value(Boolean.bare(), True) is True
    assert _serialize_value(Char.bare(), "hello") == "hello"

    m2o = Many2one.bare("res.partner")
    rec = MagicMock(_ids=[42])
    assert _serialize_value(m2o, rec) == 42
    assert _serialize_value(m2o, 7) == 7

    m2m = Many2many.bare("res.groups")
    m2m_rec = MagicMock(_ids=[1, 2])
    assert _serialize_value(m2m, m2m_rec) == [1, 2]
    assert _serialize_value(m2m, [3, 4]) == [3, 4]


def test_lifecycle_log_event_skips_without_registry():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import log_event

    env = MagicMock()
    env.registry = {}
    log_event(env, 1, "created")


def test_lifecycle_track_write_empty_values():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import track_write

    track_write(MagicMock(), 1, {})


def test_lifecycle_track_delete():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import track_delete

    events: list[str] = []
    import system_audit.lifecycle as lifecycle_mod

    lifecycle_mod.log_event = lambda _e, _u, event, detail=None: events.append(event)  # type: ignore[assignment]
    track_delete(MagicMock(), 3)
    assert events == ["deleted"]
