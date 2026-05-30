"""Tests for ``pyvelm.cron.CronJob``."""
from __future__ import annotations

import io
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm.tests.support.db import DatabaseTestCase


def _registry():
    reg = Registry()
    with reg.activate():

        class Target(BaseModel):
            _name = "test.cron.target"
            _table = "test_cron_target"
            label = Char()

        from pyvelm.actions import ServerAction
        from pyvelm.automation import AutomatedAction
        from pyvelm.cron import CronJob

        reg.register(Target)
        reg.register(ServerAction)
        reg.register(AutomatedAction)
        reg.register(CronJob)
    return reg


# Load CronJob once while the test registry is active.
_CRON_REG = _registry()
from pyvelm.cron import CronJob  # noqa: E402


def _cron_env(jobs):
    """Build a minimal env mock for ``CronJob.run_due``."""
    @contextmanager
    def _txn():
        yield

    actions: dict[int, MagicMock] = {}

    def _browse(action_id):
        return actions[action_id]

    env = MagicMock()
    env.registry = {"ir.cron": CronJob}
    env._acl_bypass = False
    env.transaction = _txn
    cron_model = MagicMock()
    cron_model.search.return_value = jobs
    server_model = MagicMock()
    server_model.browse.side_effect = _browse
    target_models: dict[str, MagicMock] = {}

    def _model(name: str) -> MagicMock:
        if name not in target_models:
            rs = MagicMock()
            m = MagicMock()
            m.search.return_value = rs
            target_models[name] = m
        return target_models[name]

    def _getitem(_s, key: str):
        if key == "ir.cron":
            return cron_model
        if key == "ir.actions.server":
            return server_model
        return _model(key)

    env.__getitem__ = _getitem
    return env, actions


class CronRunDueUnitTests(unittest.TestCase):
    def test_run_due_without_model_in_registry(self):
        env = MagicMock()
        env.registry = {}
        self.assertEqual(CronJob.run_due(env), [])

    def test_run_due_skips_future_nextcall(self):
        job = MagicMock()
        job.nextcall = datetime.utcnow() + timedelta(days=1)
        job.action_id = MagicMock(id=1)
        env, _ = _cron_env([job])
        self.assertEqual(CronJob.run_due(env), [])

    def test_run_due_skips_no_action(self):
        job = MagicMock()
        job.nextcall = datetime.utcnow() - timedelta(hours=1)
        job.action_id = None
        env, _ = _cron_env([job])
        self.assertEqual(CronJob.run_due(env), [])

    def test_run_due_executes_and_returns_name(self):
        job = MagicMock()
        job.name = "Hourly"
        job.nextcall = datetime.utcnow() - timedelta(hours=2)
        job.action_id = MagicMock(id=7)
        job.interval_number = 1
        job.interval_type = "hours"
        action = MagicMock()
        action.name = "Tick"
        action.model = "test.model"
        action.target_model_available.return_value = True
        env, actions = _cron_env([job])
        actions[7] = action
        with patch("sys.stderr", io.StringIO()):
            executed = CronJob.run_due(env)
        self.assertEqual(executed, ["Hourly"])
        action.run.assert_called_once()
        job.write.assert_called()

    def test_run_due_skips_missing_model_test_cron_cleanup(self):
        job = MagicMock()
        job.name = "Test cron"
        job.nextcall = datetime.utcnow() - timedelta(hours=1)
        job.action_id = MagicMock(id=3)
        job.interval_number = 1
        job.interval_type = "hours"
        action = MagicMock()
        action.name = "Cron tick"
        action.model = "missing.model"
        action.target_model_available.return_value = False
        env, actions = _cron_env([job])
        actions[3] = action
        with patch("sys.stderr", io.StringIO()):
            executed = CronJob.run_due(env)
        self.assertEqual(executed, [])
        job.unlink.assert_called_once()
        action.unlink.assert_called_once()

    def test_run_due_skips_uninstalled_model_non_test_cron(self):
        job = MagicMock()
        job.name = "Production job"
        job.nextcall = datetime.utcnow() - timedelta(hours=1)
        job.action_id = MagicMock(id=9)
        job.interval_number = 2
        job.interval_type = "days"
        action = MagicMock()
        action.name = "Prod action"
        action.model = "missing.model"
        action.target_model_available.return_value = False
        env, actions = _cron_env([job])
        actions[9] = action
        with patch("sys.stderr", io.StringIO()):
            executed = CronJob.run_due(env)
        self.assertEqual(executed, [])
        job.write.assert_called()
        job.unlink.assert_not_called()

    def test_run_due_advances_on_action_failure(self):
        job = MagicMock()
        job.name = "Flaky"
        job.nextcall = datetime.utcnow() - timedelta(hours=1)
        job.action_id = MagicMock(id=5)
        job.interval_number = 1
        job.interval_type = "hours"
        action = MagicMock()
        action.name = "Boom"
        action.model = "x"
        action.target_model_available.return_value = True
        action.run.side_effect = RuntimeError("boom")
        env, actions = _cron_env([job])
        actions[5] = action
        with patch("sys.stderr", io.StringIO()):
            executed = CronJob.run_due(env)
        self.assertEqual(executed, [])
        job.write.assert_called()


class CronRunNowUnitTests(unittest.TestCase):
    def test_run_now_without_action_raises(self):
        job = MagicMock()
        job.name = "Empty"
        job.action_id = None
        job.ensure_one = MagicMock()
        job.env = MagicMock()
        with self.assertRaises(RuntimeError):
            CronJob.run_now(job)

    def test_run_now_executes_action(self):
        job = MagicMock()
        job.name = "Now"
        job.action_id = MagicMock(id=2)
        job.interval_number = 1
        job.interval_type = "hours"
        job.ensure_one = MagicMock()

        @contextmanager
        def _txn():
            yield

        env = MagicMock()
        env._acl_bypass = False
        env.transaction = _txn
        action = MagicMock()
        action.name = "Act"
        action.model = "test.model"
        action.target_model_available.return_value = True
        target = MagicMock()
        target.search.return_value = MagicMock()
        env.__getitem__ = lambda _s, k: (
            MagicMock(browse=lambda _i: action)
            if k == "ir.actions.server"
            else target
        )
        job.env = env
        CronJob.run_now(job)
        action.run.assert_called_once_with(target.search.return_value)
        job.write.assert_called()

    def test_run_now_missing_target_model_raises(self):
        job = MagicMock()
        job.name = "Bad target"
        job.action_id = MagicMock(id=1)
        job.ensure_one = MagicMock()
        env = MagicMock()
        env._acl_bypass = False

        @contextmanager
        def _txn():
            yield

        env.transaction = _txn
        action = MagicMock()
        action.name = "Act"
        action.model = "nope"
        action.target_model_available.return_value = False
        env.__getitem__ = lambda _s, k: MagicMock(browse=lambda _i: action)
        job.env = env
        with self.assertRaises(RuntimeError):
            CronJob.run_now(job)


class CronJobIntegrationTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reg = _registry()
        cls.reg.init_db(cls.conn)
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        cls.env._acl_bypass = True
        cls.Cron = cls.env["ir.cron"]
        cls.Action = cls.env["ir.actions.server"]
        cls.Target = cls.env["test.cron.target"]

    def setUp(self):
        self.Cron.search([]).unlink()
        self.Action.search([]).unlink()
        self.Target.search([]).unlink()

    def _write_action(self, code: str = ""):
        return self.Action.create({
            "name": "Cron action",
            "model": "test.cron.target",
            "action_type": "code",
            "code": code,
        })

    def test_run_due_executes_overdue_job(self):
        self.Target.create({"label": "before"})
        action = self._write_action("records.write({'label': 'after'})")
        past = datetime.utcnow() - timedelta(hours=2)
        self.Cron.create({
            "name": "Hourly",
            "action_id": action,
            "interval_number": 1,
            "interval_type": "hours",
            "nextcall": past,
            "active": True,
        })
        executed = self.Cron.run_due(self.env)
        self.assertIn("Hourly", executed)
        self.assertEqual(self.Target.search([]).label, "after")

    def test_run_now_advances_schedule(self):
        action = self._write_action()
        job = self.Cron.create({
            "name": "Manual",
            "action_id": action,
            "interval_number": 1,
            "interval_type": "days",
            "active": True,
        })
        job.run_now()
        self.assertIsNotNone(job.lastcall)
        self.assertIsNotNone(job.nextcall)
