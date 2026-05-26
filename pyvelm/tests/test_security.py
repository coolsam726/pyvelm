"""Tests for ``pyvelm.security`` and ``Environment.has_access``."""

from __future__ import annotations

import sys
import unittest

from pyvelm import BUILTIN_MODULE_ROOTS
from pyvelm.security import _perm_dict, grant_model_access


class ChromeAttachmentUrlTests(unittest.TestCase):
    """`attachment_id_from_download_url` — backfill URL parsing."""

    @classmethod
    def setUpClass(cls):
        root = str(BUILTIN_MODULE_ROOTS[0])
        if root not in sys.path:
            sys.path.insert(0, root)
        from base import hooks  # noqa: E402

        cls.parse = staticmethod(hooks.attachment_id_from_download_url)

    def test_extracts_id_from_download_url(self):
        self.assertEqual(self.parse("/api/attachment/42/download"), 42)

    def test_ignores_external_and_empty(self):
        self.assertIsNone(self.parse("https://cdn.example/logo.png"))
        self.assertIsNone(self.parse(""))
        self.assertIsNone(self.parse(None))


class CharFieldTests(unittest.TestCase):
    def test_false_and_empty_normalize_to_none(self):
        from pyvelm.fields import Char

        f = Char()
        self.assertIsNone(f.to_python(False))
        self.assertIsNone(f.to_sql_param(False))
        self.assertIsNone(f.to_python(""))
        self.assertEqual(f.to_python("https://x.test/a.png"), "https://x.test/a.png")


class PermSpecTests(unittest.TestCase):
    def test_crud_spec(self):
        perms = _perm_dict("crud")
        self.assertTrue(perms["read"])
        self.assertTrue(perms["write"])
        self.assertTrue(perms["create"])
        self.assertTrue(perms["unlink"])

    def test_read_spec(self):
        perms = _perm_dict("read")
        self.assertTrue(perms["read"])
        self.assertFalse(perms["create"])


class HasAccessTests(unittest.TestCase):
    def test_superuser_always_granted(self):
        from pyvelm.env import Environment
        from pyvelm.registry import Registry

        reg = Registry()
        env = Environment(None, registry=reg, uid=1)
        self.assertTrue(env.has_access("any.model", "read"))
        self.assertTrue(env.access_flags("any.model")["unlink"])


class SudoTests(unittest.TestCase):
    """`Environment.sudo` / `BaseModel.sudo` mechanics (no DB needed)."""

    def _env(self, uid=7):
        from pyvelm.env import Environment
        from pyvelm.registry import Registry

        return Environment(None, registry=Registry(), uid=uid)

    def test_sudo_sets_bypass_and_keeps_uid(self):
        env = self._env(uid=7)
        su = env.sudo()
        self.assertTrue(su._acl_bypass)
        self.assertEqual(su.uid, 7)  # real user preserved (audit trail)
        self.assertTrue(su.has_access("any.model", "unlink"))
        # Original env is untouched — sudo derives a sibling.
        self.assertFalse(env._acl_bypass)

    def test_sudo_false_returns_enforced_env(self):
        env = self._env()
        self.assertFalse(env.sudo().sudo(False)._acl_bypass)

    def test_sudo_is_idempotent_returns_self(self):
        env = self._env()
        self.assertIs(env.sudo(False), env)  # already enforced
        su = env.sudo()
        self.assertIs(su.sudo(), su)  # already sudo

    def test_sudo_survives_with_context_and_company(self):
        env = self._env()
        self.assertTrue(env.sudo().with_context(x=1)._acl_bypass)
        self.assertTrue(env.sudo().with_company(3)._acl_bypass)
        # And it shares the value cache across the derivation.
        self.assertIs(env.sudo().cache, env.cache)

    def test_recordset_sudo_rebinds_env(self):
        from pyvelm import BaseModel, Char, Environment, Registry

        reg = Registry()
        with reg.activate():

            class Thing(BaseModel):
                _name = "test.su.thing"
                name = Char()

        env = Environment(None, registry=reg, uid=9)
        rs = env["test.su.thing"].browse([1, 2])
        su = rs.sudo()
        self.assertTrue(su.env._acl_bypass)
        self.assertEqual(su.env.uid, 9)
        self.assertEqual(su._ids, (1, 2))
        self.assertFalse(rs.env._acl_bypass)  # original recordset untouched


class _FakeEnv:
    """Minimal env stub: grants only the (model, perm) pairs given."""

    def __init__(self, granted):
        self._granted = set(granted)

    def has_access(self, model, perm):
        return (model, perm) in self._granted

    def can(self, _record_or_model, action, *, perm=None, model=None, **_kw):
        # Default allow for tests that don't exercise policy gating.
        # Individual tests may monkeypatch this.
        return True


class MenuAclTests(unittest.TestCase):
    """`_menu_node_visible` — sidebar entries gated by list (read) perm."""

    def _filter(self, tree, granted_models, href_model):
        from unittest.mock import patch

        from pyvelm import render

        env = _FakeEnv(granted=[(m, "read") for m in granted_models])
        with patch.object(
            render,
            "_menu_target_model",
            side_effect=lambda _e, href: href_model.get(href),
        ):
            return [n for n in tree if render._menu_node_visible(env, n)]

    def test_filters_leaves_and_prunes_empty_groups(self):
        href_model = {
            "/web/views/admin/user.list": "res.users",
            "/web/views/crm/lead.list": "crm.lead",
            "/web/admin": None,  # custom / home — not model-backed
        }
        tree = [
            {"label": "Home", "href": "/web/admin", "children": []},
            {"label": "Settings", "href": None, "children": [
                {"label": "Users", "href": "/web/views/admin/user.list",
                 "children": []},
            ]},
            {"label": "CRM", "href": None, "children": [
                {"label": "Leads", "href": "/web/views/crm/lead.list",
                 "children": []},
            ]},
        ]
        out = self._filter(tree, {"res.users"}, href_model)
        # Home stays (custom href); Settings stays (Users readable);
        # CRM is dropped (only child unreadable).
        self.assertEqual([n["label"] for n in out], ["Home", "Settings"])

    def test_explicit_model_perm_gates_custom_href(self):
        from unittest.mock import patch

        from pyvelm import render

        node = {
            "label": "Design a report", "href": "/web/reports/build",
            "access_model": "ir.report", "access_perm": "create",
            "children": [],
        }
        with patch.object(render, "_menu_target_model",
                          side_effect=lambda _e, _h: None):
            granted = _FakeEnv(granted={("ir.report", "create")})
            self.assertTrue(render._menu_node_visible(granted, dict(node)))
            denied = _FakeEnv(granted={("ir.report", "read")})  # read != create
            self.assertFalse(render._menu_node_visible(denied, dict(node)))

    def test_explicit_perm_uses_inferred_view_model(self):
        from unittest.mock import patch

        from pyvelm import render

        node = {
            "label": "Edit leads", "href": "/web/views/crm/lead.list",
            "access_perm": "write", "children": [],
        }
        with patch.object(render, "_menu_target_model",
                          side_effect=lambda _e, _h: "crm.lead"):
            writer = _FakeEnv(granted={("crm.lead", "write")})
            self.assertTrue(render._menu_node_visible(writer, dict(node)))
            reader = _FakeEnv(granted={("crm.lead", "read")})
            self.assertFalse(render._menu_node_visible(reader, dict(node)))

    def test_access_policy_gates_visibility(self):
        from unittest.mock import patch

        from pyvelm import render

        node = {
            "label": "Approvals",
            "href": "/web/workflow/inbox",
            "access_model": "workflow.approval",
            "access_perm": "read",
            "access_policy": "view_any",
            "children": [],
        }
        with patch.object(render, "_menu_target_model", side_effect=lambda _e, _h: None):
            env = _FakeEnv(granted={("workflow.approval", "read")})
            env.can = lambda *_a, **_k: False  # deny via policy
            self.assertFalse(render._menu_node_visible(env, dict(node)))
            env2 = _FakeEnv(granted={("workflow.approval", "read")})
            env2.can = lambda *_a, **_k: True
            self.assertTrue(render._menu_node_visible(env2, dict(node)))

    def test_group_keeps_only_permitted_children(self):
        href_model = {
            "/web/views/admin/user.list": "res.users",
            "/web/views/admin/rule.list": "ir.rule",
        }
        tree = [
            {"label": "Settings", "href": None, "children": [
                {"label": "Users", "href": "/web/views/admin/user.list",
                 "children": []},
                {"label": "Rules", "href": "/web/views/admin/rule.list",
                 "children": []},
            ]},
        ]
        out = self._filter(tree, {"res.users"}, href_model)
        self.assertEqual([n["label"] for n in out], ["Settings"])
        self.assertEqual([c["label"] for c in out[0]["children"]], ["Users"])


class AccessDeniedShellTests(unittest.TestCase):
    def test_feedback_capture_uses_minimal_shell(self):
        from pyvelm.render import access_denied_use_sidebar

        self.assertFalse(
            access_denied_use_sidebar("/web/feedback_signals/capture")
        )
        self.assertTrue(access_denied_use_sidebar("/web/views/crm/lead.list"))


class HeaderActionGatingTests(unittest.TestCase):
    """`_resolve_header_actions` hides actions the user can't perform."""

    ACTIONS = [
        {"label": "Run Now", "url": "/web/cron/{id}/run-now",
         "method": "POST", "perm": "write"},
        {"label": "Open log", "url": "https://logs.example/{id}",
         "method": "GET"},  # no perm → always visible
    ]

    def _resolve(self, env):
        from pyvelm.render import _resolve_header_actions

        return _resolve_header_actions(
            self.ACTIONS, env,
            model="ir.cron", module="admin", name="cron.form", record_id=7,
        )

    def test_reader_sees_only_unguarded_action(self):
        out = self._resolve(_FakeEnv(granted=[("ir.cron", "read")]))
        labels = [a["label"] for a in out]
        self.assertEqual(labels, ["Open log"])

    def test_writer_sees_guarded_action(self):
        out = self._resolve(_FakeEnv(granted=[("ir.cron", "write")]))
        labels = [a["label"] for a in out]
        self.assertEqual(labels, ["Run Now", "Open log"])
        run = out[0]
        self.assertEqual(run["url"], "/web/cron/7/run-now")  # {id} filled
        self.assertEqual(run["method"], "POST")

    def test_perm_can_target_a_different_model(self):
        action = [{"label": "Sync", "url": "/x", "perm": "write",
                   "model": "other.model"}]
        from pyvelm.render import _resolve_header_actions

        denied = _resolve_header_actions(
            action, _FakeEnv(granted=[("ir.cron", "write")]),
            model="ir.cron", module="admin", name="cron.form", record_id=1,
        )
        self.assertEqual(denied, [])
        allowed = _resolve_header_actions(
            action, _FakeEnv(granted=[("other.model", "write")]),
            model="ir.cron", module="admin", name="cron.form", record_id=1,
        )
        self.assertEqual([a["label"] for a in allowed], ["Sync"])

    def test_external_url_flagged_full_page(self):
        out = self._resolve(_FakeEnv(granted=[("ir.cron", "write")]))
        log = next(a for a in out if a["label"] == "Open log")
        self.assertTrue(log["full_page"])


if __name__ == "__main__":
    unittest.main()
