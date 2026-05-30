"""Tests for ``pyvelm.actions.ServerAction`` (``ir.actions.server``)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm.tests.support.db import DatabaseTestCase


def _registry() -> Registry:
    reg = Registry()
    with reg.activate():

        class Target(BaseModel):
            _name = "test.action.target"
            _table = "test_action_target"
            label = Char()

        from pyvelm.actions import ServerAction
        from pyvelm.automation import AutomatedAction

        reg.register(ServerAction)
        reg.register(AutomatedAction)
    return reg


class ServerActionIntegrationTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reg = _registry()
        cls.reg.init_db(cls.conn)
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        cls.env._acl_bypass = True
        cls.Action = cls.env["ir.actions.server"]
        cls.Target = cls.env["test.action.target"]
        cls.Target.search([]).unlink()

    def setUp(self):
        self.Target.search([]).unlink()

    def _create_action(self, **fields):
        defaults = {
            "name": "Test action",
            "model": "test.action.target",
            "action_type": "write",
            "vals_json": "{}",
        }
        defaults.update(fields)
        return self.Action.create(defaults)

    def _reload(self, row):
        return self.Target.browse((row.id,))

    def test_target_model_available(self):
        action = self._create_action()
        self.assertTrue(action.target_model_available())
        missing = self._create_action(name="Missing model", model="no.such.model")
        self.assertFalse(missing.target_model_available())

    def test_write_updates_records(self):
        row = self.Target.create({"label": "before"})
        action = self._create_action(
            action_type="write",
            vals_json=json.dumps({"label": "after"}),
        )
        action.run(row)
        self.assertEqual(self._reload(row).label, "after")

    def test_write_skips_empty_recordset(self):
        action = self._create_action(
            action_type="write",
            vals_json=json.dumps({"label": "ghost"}),
        )
        action.run(self.Target.browse(()))
        self.assertEqual(self.Target.search_count([]), 0)

    def test_create_inserts_row(self):
        action = self._create_action(
            action_type="create",
            vals_json=json.dumps({"label": "created"}),
        )
        action.run()
        self.assertEqual(self.Target.search_count([("label", "=", "created")]), 1)

    def test_unlink_removes_records(self):
        row = self.Target.create({"label": "delete me"})
        row_id = row.id
        action = self._create_action(action_type="unlink")
        action.run(row)
        self.assertEqual(self.Target.search_count([("id", "=", row_id)]), 0)

    def test_unlink_skips_empty_recordset(self):
        action = self._create_action(action_type="unlink")
        action.run(self.Target.browse(()))

    def test_code_executes_against_records(self):
        row = self.Target.create({"label": "code before"})
        action = self._create_action(
            action_type="code",
            code="records.write({'label': 'code after'})",
        )
        action.run(row)
        self.assertEqual(self._reload(row).label, "code after")

    def test_run_with_none_uses_empty_model_recordset(self):
        self.Target.create({"label": "bulk-a"})
        action = self._create_action(
            action_type="write",
            vals_json=json.dumps({"label": "bulk-updated"}),
        )
        action.run()
        row = self.Target.search([("label", "=", "bulk-a")])
        self.assertEqual(len(row), 1)
        self.assertEqual(self._reload(row).label, "bulk-a")

    def test_write_all_when_recordset_passed(self):
        self.Target.create({"label": "bulk-a"})
        self.Target.create({"label": "bulk-b"})
        action = self._create_action(
            action_type="write",
            vals_json=json.dumps({"label": "bulk-updated"}),
        )
        action.run(self.Target.search([]))
        labels = {r.label for r in self.Target.search([])}
        self.assertEqual(labels, {"bulk-updated"})

    def test_unknown_model_raises(self):
        action = self._create_action(model="missing.model")
        row = self.Target.create({"label": "x"})
        with self.assertRaises(ValueError) as ctx:
            action.run(row)
        self.assertIn("missing.model", str(ctx.exception))

    def test_unknown_action_type_raises(self):
        action = self._create_action(action_type="archive")
        row = self.Target.create({"label": "x"})
        with self.assertRaises(ValueError) as ctx:
            action.run(row)
        self.assertIn("archive", str(ctx.exception))


class ServerActionMockedTests(unittest.TestCase):
    """Branches that do not need Postgres."""

    def test_write_noop_when_recordset_falsy(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        action = reg["ir.actions.server"](env, (1,))
        env.__getitem__.return_value = MagicMock()

        cache_row = {
            "name": "Mock write",
            "model": "test.action.target",
            "action_type": "write",
            "vals_json": json.dumps({"label": "nope"}),
        }
        env.cache = MagicMock()
        env.cache.get.side_effect = lambda m, i, f, default=None: cache_row.get(
            f, default
        )

        records = MagicMock()
        records.__bool__ = MagicMock(return_value=False)

        action.run(records)
        records.write.assert_not_called()

    def test_target_model_available_without_db(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        action = reg["ir.actions.server"](env, (1,))
        env.cache = MagicMock()
        env.cache.get.side_effect = lambda m, i, f, default=None: {
            "model": "test.action.target",
        }.get(f, default)
        self.assertTrue(action.target_model_available())


if __name__ == "__main__":
    unittest.main()
