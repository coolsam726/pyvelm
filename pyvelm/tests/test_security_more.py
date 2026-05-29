"""Unit tests for ``pyvelm.security`` ACL helpers."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.security import (
    GROUP_ADMIN,
    GROUP_PUBLIC,
    GROUP_USER,
    _ensure_access_row,
    _group_by_name,
    _perm_dict,
    assign_user_group_to_active_users,
    can_view_apps_catalog,
    ensure_user_group,
    grant_model_access,
    template_access,
    user_in_group,
)


class PermDictTests(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertIsNone(_perm_dict(None))
        self.assertIsNone(_perm_dict(""))

    def test_aliases(self):
        for spec in ("crud", "full", "all"):
            p = _perm_dict(spec)
            self.assertTrue(all(p[k] for k in ("read", "write", "create", "unlink")))
        rw = _perm_dict("readwrite")
        self.assertTrue(rw["read"] and rw["write"])
        self.assertFalse(rw["create"])
        ru = _perm_dict("read_unlink")
        self.assertTrue(ru["read"] and ru["unlink"])
        self.assertFalse(ru["write"])

    def test_unknown_spec_raises(self):
        with self.assertRaises(ValueError):
            _perm_dict("sudo")


class GrantModelAccessTests(unittest.TestCase):
    def _env(self, *, models=None, groups=None, access_rows=None):
        env = MagicMock()
        env.registry = models or {
            "res.groups": object,
            "ir.model.access": object,
            "test.model": object,
        }
        grp_admin = MagicMock(id=1)
        grp_user = MagicMock(id=2)
        Group = MagicMock()
        Group.search.side_effect = lambda domain, limit=1: {
            ("name", "=", GROUP_ADMIN): grp_admin,
            ("name", "=", GROUP_USER): grp_user,
        }.get(domain[0], MagicMock(_ids=()))
        Access = MagicMock()
        Access.search.return_value = access_rows or []
        env.__getitem__ = lambda _s, name: {
            "res.groups": Group,
            "ir.model.access": Access,
        }[name]
        return env, Access

    def test_skips_unknown_model(self):
        env = MagicMock()
        env.registry = {"res.groups": object, "ir.model.access": object}
        grant_model_access(env, "missing.model")
        env.__getitem__.assert_not_called()

    def test_creates_admin_and_user_rows(self):
        env, Access = self._env()
        grant_model_access(env, "test.model", admin="crud", user="read", public="read")
        self.assertGreaterEqual(Access.create.call_count, 2)
        names = {c.args[0]["name"] for c in Access.create.call_args_list}
        self.assertIn(f"Admin/test.model", names)
        self.assertIn(f"User/test.model", names)
        self.assertIn(f"Public/test.model", names)

    def test_skips_when_group_missing(self):
        env = MagicMock()
        env.registry = {
            "res.groups": object,
            "ir.model.access": object,
            "test.model": object,
        }
        Group = MagicMock()
        Group.search.return_value = None
        Access = MagicMock()
        Access.search.return_value = []
        env.__getitem__ = lambda _s, n: Group if n == "res.groups" else Access
        grant_model_access(env, "test.model", admin="crud", user="read")
        Access.create.assert_not_called()

    def test_idempotent_when_row_exists(self):
        env, Access = self._env(access_rows=[MagicMock()])
        grant_model_access(env, "test.model")
        Access.create.assert_not_called()

    def test_no_ir_model_access_registry(self):
        env = MagicMock()
        env.registry = {"test.model": object, "res.groups": object}
        grant_model_access(env, "test.model")
        # no raise

    def test_ensure_access_row_without_access_model(self):
        env = MagicMock()
        env.registry = {"res.groups": object}
        _ensure_access_row(
            env,
            name="x",
            model="m",
            group=MagicMock(),
            perms=_perm_dict("read"),
        )


class EnsureUserGroupTests(unittest.TestCase):
    def test_returns_none_without_groups_model(self):
        env = MagicMock()
        env.registry = {}
        self.assertIsNone(ensure_user_group(env))

    def test_returns_existing_group(self):
        env = MagicMock()
        env.registry = {"res.groups": object}
        grp = MagicMock()
        Group = MagicMock()
        Group.search.return_value = grp
        env.__getitem__ = lambda _s, n: Group
        self.assertIs(ensure_user_group(env), grp)
        Group.create.assert_not_called()

    def test_creates_group_when_missing(self):
        env = MagicMock()
        env.registry = {"res.groups": object}
        Group = MagicMock()
        Group.search.return_value = None
        created = MagicMock()
        Group.create.return_value = created
        env.__getitem__ = lambda _s, n: Group
        self.assertIs(ensure_user_group(env), created)
        Group.create.assert_called_once_with({"name": GROUP_USER})


class AssignUserGroupTests(unittest.TestCase):
    def test_noop_without_users(self):
        env = MagicMock()
        env.registry = {"res.groups": object}
        assign_user_group_to_active_users(env)

    def test_noop_when_user_group_missing(self):
        env = MagicMock()
        env.registry = {"res.users": object, "res.groups": object}
        with patch("pyvelm.security.ensure_user_group", return_value=None):
            assign_user_group_to_active_users(env)

    def test_skips_superuser(self):
        env = MagicMock()
        env.registry = {"res.users": object, "res.groups": object}
        env.SUPERUSER_ID = 1
        grp = MagicMock(id=99)
        superuser = MagicMock(id=1)
        superuser.group_ids.ids = []
        normal = MagicMock(id=2)
        normal.group_ids.ids = []
        User = MagicMock()
        User.search.return_value = [superuser, normal]
        sudo_env = MagicMock()
        sudo_env.__getitem__ = lambda _s, n: User
        env.sudo.return_value = sudo_env
        env.__getitem__ = lambda _s, n: MagicMock(search=lambda *a, **k: grp)
        with patch("pyvelm.security.ensure_user_group", return_value=grp):
            assign_user_group_to_active_users(env)
        superuser.write.assert_not_called()
        normal.write.assert_called_once()

    def test_skips_user_already_in_group(self):
        env = MagicMock()
        env.registry = {"res.users": object, "res.groups": object}
        env.SUPERUSER_ID = 1
        grp = MagicMock(id=99)
        user = MagicMock(id=2)
        user.group_ids.ids = [99, 10]
        User = MagicMock()
        User.search.return_value = [user]
        sudo_env = MagicMock()
        sudo_env.__getitem__ = lambda _s, n: User
        env.sudo.return_value = sudo_env
        env.__getitem__ = lambda _s, n: MagicMock(search=lambda *a, **k: grp)
        with patch("pyvelm.security.ensure_user_group", return_value=grp):
            assign_user_group_to_active_users(env)
        user.write.assert_not_called()

    def test_adds_group_to_active_users(self):
        env = MagicMock()
        env.registry = {"res.users": object, "res.groups": object}
        env.SUPERUSER_ID = 1
        grp = MagicMock(id=99)
        user = MagicMock(id=2)
        user.group_ids.ids = [10]
        User = MagicMock()
        User.search.return_value = [user]
        Group = MagicMock()
        Group.search.return_value = grp
        sudo_env = MagicMock()
        sudo_env.__getitem__ = lambda _s, n: User
        env.sudo.return_value = sudo_env

        def getitem(name):
            return Group if name == "res.groups" else User

        env.__getitem__ = getitem
        with patch("pyvelm.security.ensure_user_group", return_value=grp):
            assign_user_group_to_active_users(env)
        user.write.assert_called_once()
        self.assertIn(99, user.write.call_args[0][0]["group_ids"])


class CanViewAppsCatalogTests(unittest.TestCase):
    def test_superuser(self):
        env = MagicMock()
        env.is_superuser.return_value = True
        self.assertTrue(can_view_apps_catalog(env))

    def test_without_users_model(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.registry = {}
        self.assertFalse(can_view_apps_catalog(env))

    def test_checks_view_any_policy(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.registry = {"res.users": object}
        env.can.return_value = True
        self.assertTrue(can_view_apps_catalog(env))
        env.can.assert_called_once_with("res.users", "view_any", perm="read")


class UserInGroupTests(unittest.TestCase):
    def test_superuser(self):
        env = MagicMock()
        env.is_superuser.return_value = True
        self.assertTrue(user_in_group(env, GROUP_ADMIN))

    def test_no_uid(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.uid = None
        self.assertFalse(user_in_group(env, GROUP_USER))

    def test_member_when_group_present(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.uid = 5
        env.registry = {"res.users": object, "res.groups": object}
        grp = MagicMock(id=3)
        user = MagicMock()
        user.exists.return_value = True
        user.group_ids.ids = [3, 7]
        Group = MagicMock()
        Group.search.return_value = grp
        User = MagicMock()
        User.browse.return_value = user
        env.__getitem__ = lambda _s, n: Group if n == "res.groups" else User
        self.assertTrue(user_in_group(env, GROUP_ADMIN))

    def test_not_member_when_group_missing(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.uid = 5
        env.registry = {"res.users": object, "res.groups": object}
        Group = MagicMock()
        Group.search.return_value = None
        env.__getitem__ = lambda _s, n: Group
        self.assertFalse(user_in_group(env, GROUP_USER))

    def test_not_member_when_user_missing(self):
        env = MagicMock()
        env.is_superuser.return_value = False
        env.uid = 5
        env.registry = {"res.users": object, "res.groups": object}
        grp = MagicMock(id=3)
        user = MagicMock()
        user.exists.return_value = False
        Group = MagicMock()
        Group.search.return_value = grp
        User = MagicMock()
        User.browse.return_value = user
        env.__getitem__ = lambda _s, n: Group if n == "res.groups" else User
        self.assertFalse(user_in_group(env, GROUP_USER))


class TemplateAccessTests(unittest.TestCase):
    def test_maps_access_flags(self):
        env = MagicMock()
        env.access_flags.return_value = {
            "read": True,
            "write": False,
            "create": True,
            "unlink": False,
        }
        out = template_access(env, "crm.lead")
        self.assertEqual(out["can_read"], True)
        self.assertEqual(out["can_write"], False)
        env.access_flags.assert_called_once_with("crm.lead")


class GroupByNameTests(unittest.TestCase):
    def test_missing_registry(self):
        env = MagicMock()
        env.registry = {}
        self.assertIsNone(_group_by_name(env, GROUP_ADMIN))

    def test_search(self):
        env, _ = GrantModelAccessTests()._env()
        grp = _group_by_name(env, GROUP_ADMIN)
        self.assertIsNotNone(grp)


if __name__ == "__main__":
    unittest.main()
