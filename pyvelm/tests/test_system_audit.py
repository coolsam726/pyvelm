"""Tests for the bundled ``system_audit`` module."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry

# Unit tests import ``system_audit.*`` like installed addons do.
_MODULES_PARENT = Path(__file__).resolve().parents[1] / "modules"
if str(_MODULES_PARENT) not in sys.path:
    sys.path.insert(0, str(_MODULES_PARENT))
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
    from unittest.mock import MagicMock, patch

    import system_audit.lifecycle as lifecycle_mod
    from system_audit.lifecycle import track_create

    events: list[str] = []

    def _capture(_e, _u, event, detail=None):
        events.append(event)

    with patch.object(lifecycle_mod, "log_event", _capture):
        track_create(MagicMock(), 4, {"name": "Ann", "email": "a@b.c"})
    assert events == ["created"]


def test_lifecycle_password_and_groups_events():
    from unittest.mock import MagicMock, patch

    import system_audit.lifecycle as lifecycle_mod
    from system_audit.lifecycle import track_write

    created: list[tuple] = []

    def _log(env, user_id, event, detail=None):
        created.append((event, detail))

    with patch.object(lifecycle_mod, "log_event", _log):
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


def test_logger_company_id_from_scalar_values():
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
    log_crud(
        env,
        "res.partner",
        4,
        "write",
        old_values={"company_id": 12},
        new_values={},
    )
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
    from unittest.mock import MagicMock, patch

    import system_audit.lifecycle as lifecycle_mod
    from system_audit.lifecycle import track_delete

    events: list[str] = []

    def _capture(_e, _u, event, detail=None):
        events.append(event)

    with patch.object(lifecycle_mod, "log_event", _capture):
        track_delete(MagicMock(), 3)
    assert events == ["deleted"]


def test_lifecycle_log_event_persists():
    from unittest.mock import MagicMock

    from system_audit.lifecycle import log_event

    created: list[dict] = []
    model = MagicMock()
    model.create.side_effect = lambda vals: created.append(vals) or MagicMock()
    sudo = MagicMock()
    sudo.__getitem__.return_value = model
    env = MagicMock()
    env.registry = {"ir.user.lifecycle": object()}
    env.uid = 1
    env.sudo.return_value = sudo
    log_event(env, 8, "activated", {"active": True})
    assert len(created) == 1
    assert created[0]["event"] == "activated"
    assert created[0]["user_id"] == 8
    assert '"active": true' in created[0]["detail"].lower()


def test_lifecycle_track_write_activation_toggle():
    from unittest.mock import MagicMock, patch

    import system_audit.lifecycle as lifecycle_mod
    from system_audit.lifecycle import track_write

    events: list[str] = []

    def _capture(_e, _u, event, detail=None):
        events.append(event)

    with patch.object(lifecycle_mod, "log_event", _capture):
        track_write(MagicMock(), 2, {"active": True}, {"active": False})
    assert events == ["activated"]


def test_listener_fire_hooks_early_returns_and_users():
    from unittest.mock import MagicMock, patch

    from system_audit.listener import fire_on_create, fire_on_unlink, fire_on_write

    record = MagicMock()
    record._name = "res.partner"
    record.id = 3

    env = MagicMock()
    env.registry = {}
    fire_on_create(env, record, {"name": "x"})

    env.registry = {"ir.audit.log": object()}
    records = MagicMock()
    records._name = "ir.audit.log"
    records._ids = [1]
    with patch("system_audit.listener.log_crud") as log_crud:
        fire_on_write(env, records, {"x": 1})
        log_crud.assert_not_called()

    records._ids = []
    with patch("system_audit.listener.log_crud") as log_crud:
        fire_on_write(env, records, {"x": 1})
        log_crud.assert_not_called()

    records._name = "res.users"
    records._ids = [9]
    with patch("system_audit.listener.track_delete") as track_delete:
        fire_on_unlink(env, records, before_by_id={9: {"login": "u"}})
        track_delete.assert_called_once_with(env, 9)

    records._ids = []
    with patch("system_audit.listener.log_crud") as log_crud:
        fire_on_unlink(env, records)
        log_crud.assert_not_called()


def test_listener_snapshot_record_skips_bad_fields():
    from unittest.mock import MagicMock, PropertyMock

    from pyvelm.fields import Char
    from system_audit.listener import _serialize_value, snapshot_record

    record = MagicMock()
    record._fields = {
        "name": Char.bare(),
        "computed": Char.bare(compute="x"),
        "missing": None,
        "bad": Char.bare(),
    }
    type(record).name = PropertyMock(side_effect=["ok", "ok"])
    type(record).bad = PropertyMock(side_effect=RuntimeError("boom"))
    record.__getitem__ = lambda self, key: getattr(self, key)
    out = snapshot_record(record, ["name", "computed", "missing", "bad"])
    assert out == {"name": "ok"}

    m2o = __import__("pyvelm.fields", fromlist=["Many2one"]).Many2one.bare("res.partner")
    empty = MagicMock(_ids=[])
    assert _serialize_value(m2o, empty) is None


def test_logger_skips_audit_models_and_resolves_company_ref():
    from unittest.mock import MagicMock

    from system_audit.logger import log_crud

    env = MagicMock()
    env.registry = {"ir.audit.log": object()}
    env.sudo.return_value.__getitem__.return_value.create = MagicMock()
    log_crud(env, "ir.audit.log", 1, "create")
    env.sudo.return_value.__getitem__.return_value.create.assert_not_called()

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
    company_ref = MagicMock()
    company_ref.id = 55
    log_crud(
        env,
        "res.partner",
        4,
        "write",
        old_values={},
        new_values={"company_id": company_ref},
    )
    assert created[0]["company_id"] == 55


def test_seed_retention_cron_creates_job():
    from unittest.mock import MagicMock

    from system_audit.hooks import _seed_retention_cron

    cron = MagicMock()
    cron.search.return_value = MagicMock(__bool__=lambda _s: False)
    action = MagicMock()
    action.search.return_value = MagicMock(__bool__=lambda _s: False)
    action.create.return_value = MagicMock(id=77)
    env = MagicMock()
    env.registry = {"ir.cron": object(), "ir.actions.server": object()}

    def _getitem(name):
        return cron if name == "ir.cron" else action

    env.__getitem__.side_effect = _getitem
    _seed_retention_cron(env)
    action.create.assert_called_once()
    cron.create.assert_called_once()


def test_audit_web_cell_and_export_routes():
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import system_audit.web as audit_web

    assert audit_web._cell({"a": 1}) == '{"a": 1}'
    assert audit_web._cell(SimpleNamespace(_ids=[3])) == 3
    assert audit_web._cell(SimpleNamespace(_ids=[1, 2])) == [1, 2]
    assert audit_web._cell(SimpleNamespace(id=9)) == 9

    log = SimpleNamespace(
        created_at="2026-01-01",
        name="create res.partner#1",
        model="res.partner",
        res_id=1,
        action="create",
        user_id=None,
        company_id=None,
        ip_address="1.2.3.4",
        user_agent="pytest",
    )
    model = MagicMock()
    model.search.return_value = [log]
    env = MagicMock()
    env.registry = {
        "ir.audit.log": object(),
        "ir.login.log": object(),
        "ir.user.lifecycle": object(),
    }
    env.uid = 1
    env.check_access = MagicMock()
    env.__getitem__.return_value = model

    @contextmanager
    def connection():
        yield MagicMock()

    pool = MagicMock()
    pool.connection = connection
    app = FastAPI()
    app.state.registry = MagicMock()
    app.state.pool = pool

    session_uid: list[int | None] = [1]

    def fake_apply(environment, request, **kwargs):
        environment.uid = session_uid[0]
        return environment

    with patch("system_audit.web.Environment", return_value=env), patch(
        "system_audit.web.apply_request_scope", side_effect=fake_apply
    ):
        audit_web.register_routes(app)
        with TestClient(app) as client:
            ok = client.get("/web/audit/logs/export")
            assert ok.status_code == 200
            assert "audit-log.csv" in ok.headers.get("content-disposition", "")

            session_uid[0] = None
            anon = client.get("/web/audit/logins/export")
            assert anon.status_code == 401

            session_uid[0] = 1
            env.registry = {}
            missing = client.get("/web/audit/lifecycle/export")
            assert missing.status_code == 404

            env.registry = {"ir.user.lifecycle": object()}

            def _deny(_model, _perm):
                raise PermissionError("nope")

            env.check_access.side_effect = _deny
            denied = client.get("/web/audit/lifecycle/export")
            assert denied.status_code == 403


@pytest.mark.integration
def test_login_and_logout_audit_entries(pyvelm_dsn: str):
    from fastapi.testclient import TestClient

    from pyvelm.web import create_app

    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        install_named_modules(env, ["admin", "system_audit"], list(BUILTIN_MODULE_ROOTS))

    app = create_app(reg, db, module_roots=list(BUILTIN_MODULE_ROOTS))
    with TestClient(app) as client:
        client.get("/login")
        csrf = client.cookies.get("pyvelm_csrf")
        bad = client.post(
            "/login",
            data={"login": "admin", "password": "wrong", "_csrf": csrf},
        )
        assert bad.status_code == 401

        client.get("/login")
        csrf = client.cookies.get("pyvelm_csrf")
        good = client.post(
            "/login",
            data={"login": "admin", "password": "admin", "_csrf": csrf},
            follow_redirects=False,
        )
        assert good.status_code == 303

        export = client.get("/web/audit/logs/export")
        assert export.status_code == 200
        assert "text/csv" in export.headers["content-type"]

        logout = client.post(
            "/logout",
            data={"_csrf": client.cookies.get("pyvelm_csrf")},
            follow_redirects=False,
        )
        assert logout.status_code == 303

    conn = db.open_connection()
    env = Environment(conn, registry=reg, uid=1)
    env._acl_bypass = True
    try:
        failures = env["ir.login.log"].search([("event", "=", "login_failure")])
        assert failures
        successes = env["ir.login.log"].search([("event", "=", "login_success")])
        assert successes
        logouts = env["ir.login.log"].search([("event", "=", "logout")])
        assert logouts
    finally:
        conn.close()
        db.dispose()


@pytest.mark.integration
def test_user_unlink_lifecycle_event(pyvelm_dsn: str):
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
                "name": "Gone User",
                "login": "gone.user@example.com",
                "password": "secret",
            }
        )
        user.unlink()
        deleted = env["ir.user.lifecycle"].search([("event", "=", "deleted")])
        assert deleted
        deleted.ensure_one()
        # FK is nulled after unlink; the event row itself is the audit trail.
        assert not deleted.user_id
    finally:
        conn.close()
        db.dispose()
