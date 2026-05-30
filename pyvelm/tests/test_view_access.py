"""Non-admin users must be able to read ``ir.ui.view`` (web UI arch)."""
from __future__ import annotations

import unittest

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.tests.support.db import DatabaseTestCase, install_modules


class UiViewReadAccessTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        install_modules(cls.env, BUILTIN_MODULE_ROOTS)

    def test_everyone_can_read_ir_ui_view(self):
        Access = self.env["ir.model.access"]
        grant = Access.search(
            [
                ("model", "=", "ir.ui.view"),
                ("group_id", "=", None),
                ("perm_read", "=", True),
            ],
            limit=1,
        )
        self.assertTrue(grant, "Everyone/ir.ui.view grant missing")

        User = self.env["res.users"]
        login = "view_acl_test_user"
        existing = User.search([("login", "=", login)], limit=1)
        if existing:
            user = existing
        else:
            user = User.create(
                {
                    "name": "View ACL Test",
                    "login": login,
                    "password": "test",
                    "group_ids": [],
                }
            )
        uid = user.id
        anon_env = Environment(self.conn, registry=self.reg, uid=uid)
        View = anon_env["ir.ui.view"]
        views = View.search([], limit=1)
        self.assertTrue(views)

    def test_non_admin_can_read_own_res_users_row(self):
        User = self.env["res.users"]
        login = "view_self_read_user"
        existing = User.search([("login", "=", login)], limit=1)
        if existing:
            user = existing
        else:
            user = User.create(
                {
                    "name": "Self Read",
                    "login": login,
                    "password": "test",
                    "group_ids": [],
                }
            )
        uid = user.id
        scoped = Environment(self.conn, registry=self.reg, uid=uid)
        row = scoped["res.users"].browse((uid,))
        row.ensure_one()
        self.assertEqual(row.login, login)


if __name__ == "__main__":
    unittest.main()
