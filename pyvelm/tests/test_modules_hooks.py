"""Unit tests for bundled addon ``hooks.py`` install/sync entry points."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BUILTIN_MODULE_ROOTS


def _modules_path() -> str:
    root = str(BUILTIN_MODULE_ROOTS[0])
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def _admin_group():
    grp = MagicMock()
    grp.id = 1
    grp.ensure_one = MagicMock()
    return grp


def _access_model():
    Access = MagicMock()
    Access.search.return_value = _recordset()
    Access.create = MagicMock()
    return Access


def _recordset(*rows):
    rs = MagicMock()
    rs.__iter__ = lambda self: iter(rows)
    rs.__bool__ = lambda self: bool(rows)
    return rs


class BaseHooksHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from base import hooks  # noqa: E402

        cls.hooks = hooks

    def test_classify_chrome_attachments_public(self):
        env = MagicMock()
        company_cls = type(
            "Company",
            (),
            {
                "_fields": {
                    "logo_url": True,
                    "logo_url_dark": True,
                    "favicon_url": True,
                }
            },
        )
        env.registry = {"ir.attachment": object(), "res.company": company_cls}
        senv = MagicMock()
        env.sudo.return_value = senv
        company = MagicMock()
        company.logo_url = "/api/attachment/5/download"
        company.logo_url_dark = None
        company.favicon_url = None
        Company = MagicMock()
        Company.search.return_value = _recordset(company)
        att = MagicMock()
        Attachment = MagicMock()
        Attachment.search.return_value = _recordset(att)
        senv.__getitem__ = lambda _s, k: Company if k == "res.company" else Attachment
        self.hooks.classify_chrome_attachments_public(env)
        att.write.assert_called_with({"public": True})


class AdminHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from admin import hooks  # noqa: E402

        cls.hooks = hooks

    def test_install_grants_admin_acl_rows(self):
        env = MagicMock()
        Group = MagicMock()
        Group.search.return_value = _admin_group()
        Access = _access_model()
        env.__getitem__ = lambda _s, k: Group if k == "res.groups" else Access
        self.hooks.install(env)
        self.assertEqual(Access.create.call_count, 4)


class TechnicalHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from technical import hooks  # noqa: E402

        cls.hooks = hooks

    def test_install_creates_when_missing(self):
        env = MagicMock()
        Group = MagicMock()
        Group.search.return_value = _admin_group()
        Access = _access_model()
        env.__getitem__ = lambda _s, k: Group if k == "res.groups" else Access
        self.hooks.install(env)
        self.assertEqual(Access.create.call_count, 3)

    def test_install_updates_existing(self):
        env = MagicMock()
        Group = MagicMock()
        Group.search.return_value = _admin_group()
        existing = MagicMock()
        rs = _recordset(existing)
        rs.write = MagicMock()
        Access = MagicMock()
        Access.search.return_value = rs
        Access.create = MagicMock()
        env.__getitem__ = lambda _s, k: Group if k == "res.groups" else Access
        self.hooks.install(env)
        rs.write.assert_called()
        Access.create.assert_not_called()


class ReportsHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from reports import hooks  # noqa: E402

        cls.hooks = hooks

    def test_install_seeds_demo_report(self):
        env = MagicMock()
        Group = MagicMock()
        Group.search.return_value = _admin_group()
        Access = _access_model()
        Report = MagicMock()
        Report.search.return_value = _recordset()
        env.__getitem__ = lambda _s, k: {
            "res.groups": Group,
            "ir.model.access": Access,
            "ir.report": Report,
        }[k]
        self.hooks.install(env)
        Report.create.assert_called_once()


class MailComposeHooksTests(unittest.TestCase):
    def test_install_calls_grant_model_access(self):
        _modules_path()
        from mail_compose import hooks  # noqa: E402

        env = MagicMock()
        with patch("pyvelm.security.grant_model_access") as grant:
            hooks.install(env)
        grant.assert_called_once_with(
            env, "mail.compose.message", admin="crud", user="crud", public=None
        )


class FileManagerHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from file_manager import hooks  # noqa: E402

        cls.hooks = hooks

    def test_install_grants_admin_and_user(self):
        env = MagicMock()
        admin = _admin_group()
        user = MagicMock()
        user.id = 2
        user.name = "User"
        Group = MagicMock()
        Group.search.side_effect = lambda domain: (
            _recordset(admin) if domain == [("name", "=", "Admin")] else _recordset(user)
        )
        Access = _access_model()
        env.__getitem__ = lambda _s, k: Group if k == "res.groups" else Access
        self.hooks.install(env)
        self.assertGreaterEqual(Access.create.call_count, 2)


class WorkflowHooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from workflow import hooks  # noqa: E402

        cls.hooks = hooks

    def test_install_grants_and_seeds_cron(self):
        env = MagicMock()
        env.registry = {
            "workflow.definition": object(),
            "ir.actions.server": object(),
            "ir.cron": object(),
            "ir.model.access": object(),
        }
        Definition = MagicMock()
        Definition.search.return_value = _recordset()
        Action = MagicMock()
        Action.search.return_value = _recordset()
        created_action = MagicMock()
        Action.create.return_value = created_action
        Cron = MagicMock()
        Cron.search.return_value = _recordset()
        with patch("pyvelm.security.grant_model_access") as grant, patch(
            "workflow.hooks._drop_legacy_user_read_on"
        ):
            env.__getitem__ = lambda _s, k: {
                "workflow.definition": Definition,
                "ir.actions.server": Action,
                "ir.cron": Cron,
            }[k]
            self.hooks.install(env)
        self.assertGreaterEqual(grant.call_count, 4)
        Action.create.assert_called_once()
        Cron.create.assert_called_once()

    def test_drop_legacy_user_read_on(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object()}
        row = MagicMock()
        Access = MagicMock()
        Access.search.return_value = _recordset(row)
        grp = MagicMock()
        grp.id = 2
        with patch("pyvelm.security._group_by_name", return_value=grp):
            env.__getitem__ = lambda _s, k: Access
            self.hooks._drop_legacy_user_read_on(env, ("workflow.instance",))
        row.unlink.assert_called_once()

    def test_seed_escalation_reuses_existing_action(self):
        env = MagicMock()
        env.registry = {
            "ir.actions.server": object(),
            "ir.cron": object(),
        }
        action = MagicMock()
        Action = MagicMock()
        Action.search.return_value = _recordset(action)
        Cron = MagicMock()
        Cron.search.return_value = _recordset()
        env.__getitem__ = lambda _s, k: Action if k == "ir.actions.server" else Cron
        self.hooks._seed_escalation_cron(env)
        Action.create.assert_not_called()
        Cron.create.assert_called_once()

    def test_sync_updates_definition(self):
        env = MagicMock()
        env.registry = {"workflow.definition": object(), "ir.cron": object(), "ir.actions.server": object()}
        Definition = MagicMock()
        existing = MagicMock()
        rs = _recordset(existing)
        rs.write = MagicMock()
        Definition.search.return_value = rs
        with patch("workflow.hooks._drop_legacy_user_read_on"), patch(
            "workflow.hooks._seed_escalation_cron"
        ):
            env.__getitem__ = lambda _s, k: Definition
            self.hooks.sync(env)
        rs.write.assert_called_once()

    def test_drop_legacy_without_access_model(self):
        env = MagicMock()
        env.registry = {}
        self.hooks._drop_legacy_user_read_on(env, ("workflow.instance",))

    def test_drop_legacy_when_user_group_missing(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object()}
        with patch("pyvelm.security._group_by_name", return_value=None):
            self.hooks._drop_legacy_user_read_on(env, ("workflow.instance",))

    def test_upsert_partner_workflow_creates_when_missing(self):
        Definition = MagicMock()
        Definition.search.return_value = _recordset()
        self.hooks._upsert_partner_workflow(Definition)
        Definition.create.assert_called_once()

    def test_seed_escalation_missing_registry(self):
        env = MagicMock()
        env.registry = {"ir.actions.server": object()}
        self.hooks._seed_escalation_cron(env)


if __name__ == "__main__":
    unittest.main()
