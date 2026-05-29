"""Unit tests for ``pyvelm.policy`` (registry + eval)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm.policy import (
    BasePolicy,
    eval_policy,
    policy_for,
    register_policy,
)


class _AllowPolicy(BasePolicy):
    def view_any(self):
        return True

    def approve(self, record):
        return record is not None


class _DenyPolicy(BasePolicy):
    def view(self, record):
        return False


class _BrokenPolicy(BasePolicy):
    def write(self, record):
        raise RuntimeError("policy exploded")


class BasePolicyDefaultsTests(unittest.TestCase):
    def test_default_methods_return_none(self):
        env = MagicMock()
        policy = BasePolicy(env, model_name="x.demo")
        self.assertIsNone(policy.view_any())
        self.assertIsNone(policy.create())
        self.assertIsNone(policy.view(MagicMock()))
        self.assertIsNone(policy.write(MagicMock()))
        self.assertIsNone(policy.unlink(MagicMock()))


class PolicyRegistryTests(unittest.TestCase):
    def setUp(self):
        self._saved = policy_for("test.policy.model")

    def tearDown(self):
        if self._saved is None:
            from pyvelm.policy import _POLICIES

            _POLICIES.pop("test.policy.model", None)
        else:
            register_policy("test.policy.model", self._saved)

    def test_register_and_lookup(self):
        register_policy("test.policy.model", _AllowPolicy)
        self.assertIs(policy_for("test.policy.model"), _AllowPolicy)

    def test_eval_without_registration(self):
        env = MagicMock()
        self.assertIsNone(
            eval_policy(env, model_name="unregistered.model", action="view")
        )

    def test_eval_missing_method(self):
        register_policy("test.policy.model", _AllowPolicy)
        env = MagicMock()
        self.assertIsNone(
            eval_policy(env, model_name="test.policy.model", action="not_defined")
        )

    def test_eval_record_action(self):
        register_policy("test.policy.model", _AllowPolicy)
        env = MagicMock()
        rec = MagicMock()
        self.assertTrue(
            eval_policy(
                env,
                model_name="test.policy.model",
                action="approve",
                record=rec,
            )
        )

    def test_eval_without_record(self):
        register_policy("test.policy.model", _AllowPolicy)
        env = MagicMock()
        self.assertTrue(
            eval_policy(
                env, model_name="test.policy.model", action="view_any", record=None
            )
        )

    def test_eval_denies(self):
        register_policy("test.policy.model", _DenyPolicy)
        env = MagicMock()
        self.assertFalse(
            eval_policy(
                env,
                model_name="test.policy.model",
                action="view",
                record=MagicMock(),
            )
        )

    def test_eval_exception_returns_false(self):
        register_policy("test.policy.model", _BrokenPolicy)
        env = MagicMock()
        self.assertFalse(
            eval_policy(
                env,
                model_name="test.policy.model",
                action="write",
                record=MagicMock(),
            )
        )

    def test_eval_empty_action(self):
        register_policy("test.policy.model", _AllowPolicy)
        env = MagicMock()
        self.assertIsNone(
            eval_policy(env, model_name="test.policy.model", action="  ")
        )


if __name__ == "__main__":
    unittest.main()
