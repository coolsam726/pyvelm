"""Unit tests for ``pyvelm.automation`` (no database)."""
from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Registry
from pyvelm.env import Environment


def _automation_registry():
    reg = Registry()
    with reg.activate():
        from pyvelm.automation import AutomatedAction, AutomationEngine

        class Target(BaseModel):
            _name = "test.auto.target"
            label = Char()

        reg.register(AutomatedAction)
    return reg, Target, AutomatedAction, AutomationEngine


class AutomationEngineTests(unittest.TestCase):
    def _env_with_rules(self, reg, rules):
        env = MagicMock()
        env.registry = reg._models
        env._acl_bypass = False
        auto = MagicMock()
        auto.search.return_value = rules
        server = MagicMock()

        def getitem(name):
            if name == "base.automation":
                return auto
            if name == "ir.actions.server":
                return server
            return reg[name](env, ())

        env.__getitem__ = MagicMock(side_effect=getitem)
        return env, auto, server

    def test_fire_noop_without_model_in_registry(self):
        _reg, Target, _Aa, Engine = _automation_registry()
        env = MagicMock(registry={})
        Engine.fire(env, "test.auto.target", "on_create", Target(MagicMock(), (1,)))

    def test_fire_skips_when_acl_bypass(self):
        reg, Target, _Aa, Engine = _automation_registry()
        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        with patch.object(env["base.automation"], "search") as search:
            Engine.fire(env, "test.auto.target", "on_write", Target(env, (1,)))
        search.assert_not_called()

    def test_fire_runs_matching_rules(self):
        reg, Target, _Aa, Engine = _automation_registry()
        rule = MagicMock(name="On write", action_id=MagicMock(id=7, _ids=(7,)))
        env, _auto, server = self._env_with_rules(reg, [rule])
        action = MagicMock()
        server.browse.return_value = action
        rec = MagicMock(_ids=(1,))
        Engine.fire(env, "test.auto.target", "on_write", rec)
        server.browse.assert_called_once_with(7)
        action.run.assert_called_once_with(rec)

    def test_fire_skips_rule_without_action(self):
        reg, Target, _Aa, Engine = _automation_registry()
        rule = MagicMock(name="Empty", action_id=None)
        env, _auto, server = self._env_with_rules(reg, [rule])
        Engine.fire(env, "test.auto.target", "on_create", MagicMock(_ids=(2,)))
        server.browse.assert_not_called()

    def test_fire_logs_action_failure(self):
        reg, Target, _Aa, Engine = _automation_registry()
        rule = MagicMock(name="Broken", action_id=MagicMock(id=3, _ids=(3,)))
        env, _auto, server = self._env_with_rules(reg, [rule])
        action = MagicMock()
        action.run.side_effect = RuntimeError("boom")
        server.browse.return_value = action
        rec = MagicMock(_ids=(3,))
        buf = StringIO()
        with patch("sys.stderr", buf):
            Engine.fire(env, "test.auto.target", "on_unlink", rec)
        self.assertIn("Broken", buf.getvalue())
        self.assertIn("boom", buf.getvalue())
        self.assertFalse(env._acl_bypass)


if __name__ == "__main__":
    unittest.main()
