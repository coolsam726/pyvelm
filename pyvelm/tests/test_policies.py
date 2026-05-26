"""Tests for built-in authorization policies."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.policies import register_builtin_policies
from pyvelm.policies.management import AdminManagementPolicy
from pyvelm.policy import eval_policy


class _FakeEnv:
    uid = 4

    def is_superuser(self):
        return False


class AdminManagementPolicyTests(unittest.TestCase):
    def setUp(self):
        register_builtin_policies()

    @patch("pyvelm.policies.management.user_in_group", return_value=False)
    def test_view_any_denies_non_admin(self, _mock):
        env = _FakeEnv()
        self.assertFalse(
            eval_policy(env, model_name="res.users", action="view_any")
        )

    @patch("pyvelm.policies.management.user_in_group", return_value=True)
    def test_view_any_allows_admin(self, _mock):
        env = _FakeEnv()
        self.assertTrue(
            eval_policy(env, model_name="res.users", action="view_any")
        )


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        register_builtin_policies()

    @patch("pyvelm.policies.workflow.user_in_group", return_value=False)
    def test_inbox_allows_non_admin_with_acl(self, _mock):
        env = _FakeEnv()
        self.assertTrue(
            eval_policy(env, model_name="workflow.approval", action="inbox")
        )

    @patch("pyvelm.policies.workflow.user_in_group", return_value=False)
    def test_approval_list_admin_only(self, _mock):
        env = _FakeEnv()
        self.assertFalse(
            eval_policy(env, model_name="workflow.approval", action="view_any")
        )


class AppsMenuGatingTests(unittest.TestCase):
    @patch("pyvelm.policies.management.user_in_group", return_value=False)
    def test_apps_menu_hidden_for_non_admin(self, _mock):
        from unittest.mock import patch as mock_patch

        from pyvelm import render
        from pyvelm.policy import eval_policy

        register_builtin_policies()
        node = {
            "label": "Apps",
            "href": "/web/apps",
            "access_model": "res.users",
            "access_policy": "view_any",
            "children": [],
        }
        env = MagicMock()
        env.has_access = lambda m, p: (m, p) == ("res.users", "read")
        env.can = lambda m, a, **kw: bool(
            eval_policy(
                env,
                model_name=kw.get("model") or m,
                action=a,
                record=None,
            )
        )
        with mock_patch.object(
            render, "_menu_target_model", side_effect=lambda _e, _h: None
        ):
            self.assertFalse(render._menu_node_visible(env, dict(node)))


class PolicyMenuGatingTests(unittest.TestCase):
    def _menu_can(self, env, model, action, *, perm="read"):
        from pyvelm.policy import eval_policy

        if perm and not env.has_access(model, perm):
            return False
        decision = eval_policy(
            env, model_name=model, action=action, record=None
        )
        if decision is None:
            return True
        return bool(decision)

    @patch("pyvelm.policies.management.user_in_group", return_value=False)
    def test_users_menu_hidden_for_sales_shell_read(self, _mock):
        from unittest.mock import patch as mock_patch

        from pyvelm import render

        register_builtin_policies()
        node = {
            "label": "Users",
            "href": "/web/views/admin/user.list",
            "access_policy": "view_any",
            "children": [],
        }
        env = MagicMock()
        env.has_access = lambda m, p: (m, p) == ("res.users", "read")
        env.can = lambda m, a, **kw: self._menu_can(
            env, kw.get("model") or m, a, perm=kw.get("perm") or "read"
        )
        with mock_patch.object(
            render,
            "_menu_target_model",
            side_effect=lambda _e, _h: "res.users",
        ):
            self.assertFalse(render._menu_node_visible(env, dict(node)))
