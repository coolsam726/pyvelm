"""Targeted tests to close coverage gaps — aim for 100% on small framework modules."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Date, Environment, Registry
from pyvelm.database import _bind_params, dialect_capabilities
from pyvelm.database.dsn import capabilities_from_dsn, normalize_dsn, to_psycopg_dsn
from pyvelm.database.postgres_admin import (
    prepare_postgres_schema_drop,
    release_postgres_schema_drop_lock,
    terminate_other_backends,
)
from pyvelm.file_icons import file_icon_key
from pyvelm.home import home_url, login_url
from pyvelm.policies.management import register_admin_policies
from pyvelm.policies.workflow import register_workflow_policies
from pyvelm.request_env import COMPANY_COOKIE, SESSION_COOKIE, apply_request_scope
from pyvelm.runtime import normalize_env


class DatabasePackageGapsTests(unittest.TestCase):
    def test_bind_params_alias(self):
        cap = dialect_capabilities("sqlite")
        out = _bind_params((date(2024, 1, 2),), cap)
        self.assertEqual(out[0], "2024-01-02")

    def test_normalize_dsn_empty_raises(self):
        with self.assertRaises(ValueError):
            normalize_dsn("   ")

    def test_to_psycopg_dsn_rejects_non_postgres(self):
        with self.assertRaises(ValueError):
            to_psycopg_dsn("sqlite:///tmp/x.db")

    def test_capabilities_from_dsn(self):
        self.assertEqual(capabilities_from_dsn("sqlite:///x.db").name, "sqlite")

    def test_postgres_admin_non_postgresql_noop(self):
        conn = MagicMock()
        conn.capabilities.name = "sqlite"
        terminate_other_backends(conn)
        prepare_postgres_schema_drop(conn, "public")
        release_postgres_schema_drop_lock(conn, "public")
        conn.execute.assert_not_called()


class RequestEnvGapsTests(unittest.TestCase):
    def test_apply_request_scope_basic_auth_and_invalid_company(self):
        env = MagicMock()
        env.uid = None
        env._user_groups_cache = "cached"
        env._access_cache = MagicMock()
        env.with_company = MagicMock(side_effect=ValueError("bad company"))
        request = MagicMock()
        request.cookies.get.side_effect = lambda k: {
            SESSION_COOKIE: None,
            COMPANY_COOKIE: "42",
        }.get(k)
        request.headers.get.side_effect = lambda k: "Bearer x" if k == "authorization" else None

        def resolve_session(_env, _token):
            return None

        def resolve_basic(_env, auth):
            self.assertEqual(auth, "Bearer x")
            return 9

        out = apply_request_scope(
            env,
            request,
            resolve_session=resolve_session,
            resolve_basic=resolve_basic,
        )
        self.assertIs(out, env)
        self.assertEqual(env.uid, 9)
        env.prime_current_user_cache.assert_called_once()
        env.with_company.assert_called_once_with(42)

    def test_apply_request_scope_ignores_bad_company_cookie(self):
        env = MagicMock()
        request = MagicMock()
        request.cookies.get.side_effect = lambda k: {
            SESSION_COOKIE: None,
            COMPANY_COOKIE: "not-a-number",
        }.get(k)
        request.headers.get.return_value = None
        out = apply_request_scope(
            env,
            request,
            resolve_session=lambda _e, _t: None,
            resolve_basic=lambda _e, _a: None,
        )
        self.assertIs(out, env)
        env.with_company.assert_not_called()


class PolicyGapsTests(unittest.TestCase):
    def test_register_helpers(self):
        register_admin_policies()
        register_workflow_policies()


class HomeGapsTests(unittest.TestCase):
    def test_home_url_empty_env_uses_default(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "   "}, clear=False):
            from pyvelm.home import DEFAULT_HOME_URL

            self.assertEqual(home_url(), DEFAULT_HOME_URL)

    def test_home_url_adds_leading_slash(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "web/admin"}, clear=False):
            self.assertEqual(home_url(), "/web/admin")

    def test_login_url_skips_next_when_dest_is_login(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "/login"}, clear=False):
            self.assertEqual(login_url(), "/login")


class FileIconGapsTests(unittest.TestCase):
    def test_mime_prefixes_and_extension_fallback(self):
        self.assertEqual(file_icon_key("text/plain"), "text")
        self.assertEqual(file_icon_key("audio/mpeg"), "audio")
        self.assertEqual(file_icon_key("video/mp4"), "video")
        self.assertEqual(file_icon_key("application/octet-stream", "readme.txt"), "text")
        self.assertEqual(file_icon_key(None, "archive.tar.gz"), "zip")
        self.assertEqual(file_icon_key(None, "unknown"), "file")


class RuntimeGapsTests(unittest.TestCase):
    def test_normalize_env_invalid(self):
        with self.assertRaises(ValueError):
            normalize_env("staging")


class DateFieldGapsTests(unittest.TestCase):
    def test_date_to_sql_param_false(self):
        self.assertIsNone(Date().to_sql_param(False))


class FileManagerHooksTests(unittest.TestCase):
    def test_install_grants_user_read_only(self):
        import importlib.util
        from pathlib import Path

        hooks_path = (
            Path(__file__).resolve().parents[1]
            / "modules"
            / "file_manager"
            / "hooks.py"
        )
        spec = importlib.util.spec_from_file_location("fm_hooks", hooks_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        env = MagicMock()
        admin = MagicMock(id=1)
        admin.ensure_one = MagicMock()
        user = MagicMock(id=2)
        Access = MagicMock()
        Group = MagicMock()
        Group.search.side_effect = [admin, user]
        Access.search.return_value = []
        env.__getitem__.side_effect = lambda n: {"ir.model.access": Access, "res.groups": Group}[n]
        mod.install(env)
        self.assertEqual(Access.create.call_count, 4)

    def test_install_updates_existing_access(self):
        import importlib.util
        from pathlib import Path

        hooks_path = (
            Path(__file__).resolve().parents[1]
            / "modules"
            / "file_manager"
            / "hooks.py"
        )
        spec = importlib.util.spec_from_file_location("fm_hooks2", hooks_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)

        env = MagicMock()
        admin = MagicMock(id=1)
        admin.ensure_one = MagicMock()
        existing = MagicMock()
        Access = MagicMock()
        Group = MagicMock()
        Group.search.side_effect = [admin, None]
        Access.search.return_value = existing
        env.__getitem__.side_effect = lambda n: {"ir.model.access": Access, "res.groups": Group}[n]
        mod.install(env)
        existing.write.assert_called()
        Access.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
