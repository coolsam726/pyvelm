"""Full coverage for ``pyvelm.modules.base.hooks``."""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BUILTIN_MODULE_ROOTS


def _modules_path() -> None:
    root = str(BUILTIN_MODULE_ROOTS[0])
    if root not in sys.path:
        sys.path.insert(0, root)


def _recordset(*rows):
    rs = MagicMock()
    rs.__iter__ = lambda self: iter(rows)
    rs.__bool__ = lambda self: bool(rows)
    if rows:
        rs.id = rows[0].id if hasattr(rows[0], "id") else 1
    return rs


def _empty_recordset():
    return _recordset()


class BaseHooksMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _modules_path()
        from base import hooks  # noqa: E402

        cls.hooks = hooks

    def test_attachment_id_from_download_url(self):
        self.assertIsNone(self.hooks.attachment_id_from_download_url(None))
        self.assertIsNone(self.hooks.attachment_id_from_download_url(""))
        self.assertIsNone(self.hooks.attachment_id_from_download_url("https://cdn/logo.png"))
        self.assertEqual(
            self.hooks.attachment_id_from_download_url("/api/attachment/42/download"),
            42,
        )

    def test_classify_early_returns_without_attachment_model(self):
        env = MagicMock()
        env.registry = {}
        self.hooks.classify_chrome_attachments_public(env)
        env.sudo.assert_not_called()

    def test_classify_skips_unknown_model_and_fields(self):
        env = MagicMock()
        env.registry = {"ir.attachment": object(), "res.company": type("C", (), {"_fields": {}})()}
        senv = MagicMock()
        env.sudo.return_value = senv
        Company = MagicMock()
        Company.search.return_value = _empty_recordset()
        senv.__getitem__ = lambda _s, k: Company
        self.hooks.classify_chrome_attachments_public(env)

    def test_classify_no_matching_urls(self):
        env = MagicMock()
        company_cls = type("Company", (), {"_fields": {"logo_url": True}})
        env.registry = {"ir.attachment": object(), "res.company": company_cls}
        senv = MagicMock()
        env.sudo.return_value = senv
        company = MagicMock()
        company.logo_url = "https://example.com/logo.png"
        Company = MagicMock()
        Company.search.return_value = _recordset(company)
        senv.__getitem__ = lambda _s, k: Company
        self.hooks.classify_chrome_attachments_public(env)

    def test_install_seeds_groups_company_user_and_access(self):
        env = MagicMock()
        env.registry = {
            "res.groups": object(),
            "res.users": object(),
            "res.company": object(),
            "res.currency": object(),
            "res.currency.rate": object(),
            "ir.model.access": object(),
            "ir.ui.view": object(),
            "ir.rule": object(),
            "ir.actions.server": object(),
            "ir.cron": object(),
            "mail.message": object(),
        }
        admin_group = MagicMock()
        admin_group.id = 1
        Group = MagicMock()
        Group.create.side_effect = [admin_group, MagicMock(), MagicMock()]
        User = MagicMock()
        usd = MagicMock()
        usd.id = 10
        Currency = MagicMock()
        Currency.search.return_value = _recordset(usd)
        Company = MagicMock()
        company = MagicMock()
        Company.create.return_value = company
        Access = MagicMock()
        Access.search.return_value = _empty_recordset()
        Action = MagicMock()
        Action.search.return_value = _empty_recordset()
        created_action = MagicMock()
        Action.create.return_value = created_action
        Cron = MagicMock()
        Cron.search.return_value = _empty_recordset()
        Rate = MagicMock()
        Rate.search.return_value = _empty_recordset()
        Rule = MagicMock()
        Rule.search.return_value = _empty_recordset()

        def getter(_env, key):
            return {
                "res.groups": Group,
                "res.users": User,
                "res.currency": Currency,
                "res.company": Company,
                "ir.model.access": Access,
                "ir.rule": Rule,
                "ir.actions.server": Action,
                "ir.cron": Cron,
                "res.currency.rate": Rate,
                "mail.message": MagicMock(),
            }[key]

        env.__getitem__ = getter
        with patch.object(self.hooks, "_seed_currencies") as seed_ccy:
            self.hooks.install(env)
        self.assertEqual(Group.create.call_count, 3)
        User.create.assert_called_once()
        seed_ccy.assert_called_once_with(env)
        self.assertGreater(Access.create.call_count, 0)

    def test_install_without_company_model(self):
        env = MagicMock()
        env.registry = {
            "res.groups": object(),
            "res.users": object(),
            "res.currency": object(),
            "res.currency.rate": object(),
        }
        admin_group = MagicMock()
        Group = MagicMock()
        Group.create.side_effect = [admin_group, MagicMock(), MagicMock()]
        User = MagicMock()
        env.__getitem__ = lambda _e, k: {"res.groups": Group, "res.users": User}[k]
        with patch.object(self.hooks, "_seed_currencies"):
            self.hooks.install(env)
        vals = User.create.call_args[0][0]
        self.assertNotIn("company_id", vals)

    def test_sync_runs_housekeeping(self):
        env = MagicMock()
        env.registry = {"ir.attachment": object()}
        with patch.object(self.hooks, "_purge_smoke_test_cron") as purge, patch.object(
            self.hooks, "_seed_ui_view_read_access"
        ), patch.object(self.hooks, "_seed_res_users_self_read"), patch.object(
            self.hooks, "_seed_res_groups_read_access"
        ), patch.object(self.hooks, "classify_chrome_attachments_public") as classify:
            self.hooks.sync(env)
        purge.assert_called_once_with(env)
        classify.assert_called_once_with(env)

    def test_purge_smoke_test_cron_missing_registry(self):
        env = MagicMock()
        env.registry = {}
        self.hooks._purge_smoke_test_cron(env)

    def test_purge_smoke_test_cron_unlinks_rows(self):
        env = MagicMock()
        env.registry = {"ir.cron": object(), "ir.actions.server": object()}
        env._acl_bypass = False
        cron = MagicMock()
        cron.name = "Test cron"
        action = MagicMock()
        action.name = "Cron tick"
        cron.action_id = action
        orphan = MagicMock()
        orphan.name = "Cron tick"
        Cron = MagicMock()
        Cron.search.return_value = _recordset(cron)
        Action = MagicMock()
        Action.search.return_value = _recordset(orphan)
        env.__getitem__ = lambda _e, k: Cron if k == "ir.cron" else Action
        env.transaction.return_value.__enter__ = lambda *a: None
        env.transaction.return_value.__exit__ = lambda *a: None
        self.hooks._purge_smoke_test_cron(env)
        cron.unlink.assert_called_once()
        action.unlink.assert_called_once()
        orphan.unlink.assert_called_once()

    def test_seed_ui_view_read_access_creates_when_missing(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object(), "ir.ui.view": object()}
        Access = MagicMock()
        Access.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Access
        self.hooks._seed_ui_view_read_access(env)
        Access.create.assert_called_once()

    def test_seed_ui_view_read_access_skips_when_exists(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object(), "ir.ui.view": object()}
        Access = MagicMock()
        Access.search.return_value = _recordset(MagicMock())
        env.__getitem__ = lambda _e, k: Access
        self.hooks._seed_ui_view_read_access(env)
        Access.create.assert_not_called()

    def test_seed_ui_view_read_access_without_view_model(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object()}
        self.hooks._seed_ui_view_read_access(env)

    def test_seed_res_users_self_read_without_users_model(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object(), "ir.rule": object()}
        self.hooks._seed_res_users_self_read(env)

    def test_seed_res_groups_read_access_without_groups_model(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object()}
        self.hooks._seed_res_groups_read_access(env)

    def test_seed_res_groups_read_access_skips_when_exists(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object(), "res.groups": object()}
        Access = MagicMock()
        Access.search.return_value = _recordset(MagicMock())
        env.__getitem__ = lambda _e, k: Access
        self.hooks._seed_res_groups_read_access(env)
        Access.create.assert_not_called()

    def test_seed_currencies_without_models(self):
        env = MagicMock()
        env.registry = {}
        self.hooks._seed_currencies(env)
        env.registry = {"res.currency": object()}
        self.hooks._seed_currencies(env)

    def test_seed_mail_dispatcher_missing_dependencies(self):
        env = MagicMock()
        env.registry = {}
        self.hooks._seed_mail_dispatcher(env)
        env.registry = {"ir.actions.server": object()}
        self.hooks._seed_mail_dispatcher(env)
        env.registry = {"ir.actions.server": object(), "ir.cron": object()}
        self.hooks._seed_mail_dispatcher(env)

    def test_seed_rate_fetcher_missing_dependencies(self):
        env = MagicMock()
        env.registry = {}
        self.hooks._seed_rate_fetcher(env)
        env.registry = {"ir.actions.server": object()}
        self.hooks._seed_rate_fetcher(env)
        env.registry = {"ir.actions.server": object(), "ir.cron": object()}
        self.hooks._seed_rate_fetcher(env)

    def test_seed_res_users_self_read_creates_access_and_rule(self):
        env = MagicMock()
        env.registry = {
            "ir.model.access": object(),
            "ir.rule": object(),
            "res.users": object(),
        }
        Access = MagicMock()
        Access.search.return_value = _empty_recordset()
        Rule = MagicMock()
        Rule.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Access if k == "ir.model.access" else Rule
        self.hooks._seed_res_users_self_read(env)
        Access.create.assert_called_once()
        Rule.create.assert_called_once()

    def test_seed_res_users_self_read_skips_existing(self):
        env = MagicMock()
        env.registry = {
            "ir.model.access": object(),
            "ir.rule": object(),
            "res.users": object(),
        }
        Access = MagicMock()
        Access.search.return_value = _recordset(MagicMock())
        Rule = MagicMock()
        Rule.search.return_value = _recordset(MagicMock())
        env.__getitem__ = lambda _e, k: Access if k == "ir.model.access" else Rule
        self.hooks._seed_res_users_self_read(env)
        Access.create.assert_not_called()
        Rule.create.assert_not_called()

    def test_seed_res_groups_read_access(self):
        env = MagicMock()
        env.registry = {"ir.model.access": object(), "res.groups": object()}
        Access = MagicMock()
        Access.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Access
        self.hooks._seed_res_groups_read_access(env)
        Access.create.assert_called_once()

    def test_seed_currencies_creates_new_and_rate(self):
        env = MagicMock()
        env.registry = {"res.currency": object(), "res.currency.rate": object()}
        Currency = MagicMock()
        Currency.search.return_value = _empty_recordset()
        created = MagicMock()
        created.id = 5
        Currency.create.return_value = created
        Rate = MagicMock()
        Rate.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Currency if k == "res.currency" else Rate
        self.hooks._seed_currencies(env)
        self.assertGreater(Currency.create.call_count, 0)
        self.assertGreater(Rate.create.call_count, 0)

    def test_seed_currencies_reuses_existing_currency(self):
        env = MagicMock()
        env.registry = {"res.currency": object(), "res.currency.rate": object()}
        existing = MagicMock()
        existing.id = 7
        Currency = MagicMock()
        Currency.search.return_value = _recordset(existing)
        Rate = MagicMock()
        Rate.search.return_value = _recordset(MagicMock())
        env.__getitem__ = lambda _e, k: Currency if k == "res.currency" else Rate
        self.hooks._seed_currencies(env)
        Currency.create.assert_not_called()
        Rate.create.assert_not_called()

    def test_seed_mail_dispatcher_creates_rows(self):
        env = MagicMock()
        env.registry = {
            "ir.actions.server": object(),
            "ir.cron": object(),
            "mail.message": object(),
        }
        Action = MagicMock()
        Action.search.return_value = _empty_recordset()
        created = MagicMock()
        Action.create.return_value = created
        Cron = MagicMock()
        Cron.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Action if k == "ir.actions.server" else Cron
        self.hooks._seed_mail_dispatcher(env)
        Action.create.assert_called_once()
        Cron.create.assert_called_once()

    def test_seed_mail_dispatcher_reuses_existing_action(self):
        env = MagicMock()
        env.registry = {
            "ir.actions.server": object(),
            "ir.cron": object(),
            "mail.message": object(),
        }
        action = MagicMock()
        Action = MagicMock()
        Action.search.return_value = _recordset(action)
        Cron = MagicMock()
        Cron.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Action if k == "ir.actions.server" else Cron
        self.hooks._seed_mail_dispatcher(env)
        Action.create.assert_not_called()
        Cron.create.assert_called_once()

    def test_seed_rate_fetcher_creates_inactive_cron(self):
        env = MagicMock()
        env.registry = {
            "ir.actions.server": object(),
            "ir.cron": object(),
            "res.currency.rate": object(),
        }
        Action = MagicMock()
        Action.search.return_value = _empty_recordset()
        Action.create.return_value = MagicMock()
        Cron = MagicMock()
        Cron.search.return_value = _empty_recordset()
        env.__getitem__ = lambda _e, k: Action if k == "ir.actions.server" else Cron
        self.hooks._seed_rate_fetcher(env)
        Cron.create.assert_called_once()
        self.assertFalse(Cron.create.call_args[0][0]["active"])


if __name__ == "__main__":
    unittest.main()
