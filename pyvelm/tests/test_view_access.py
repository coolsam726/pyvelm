"""Non-admin users must be able to read ``ir.ui.view`` (web UI arch)."""
from __future__ import annotations

import os
import unittest

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

DSN = os.environ.get("PYVELM_DSN")


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class UiViewReadAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(BUILTIN_MODULE_ROOTS, cls.env)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

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
        env2 = Environment(self.conn, registry=self.reg, uid=user.id)
        views = env2["ir.ui.view"].search([], limit=1)
        self.assertTrue(views)

    def test_non_admin_can_read_own_res_users_row(self):
        User = self.env["res.users"]
        login = "users_acl_test"
        existing = User.search([("login", "=", login)], limit=1)
        if existing:
            user = existing
        else:
            user = User.create(
                {
                    "name": "Users ACL Test",
                    "login": login,
                    "password": "test",
                    "group_ids": [],
                }
            )
        env2 = Environment(self.conn, registry=self.reg, uid=user.id)
        found = env2["res.users"].search([("id", "=", user.id)], limit=1)
        self.assertTrue(found)
        found.ensure_one()
        self.assertEqual(found.name, "Users ACL Test")


if __name__ == "__main__":
    unittest.main()
