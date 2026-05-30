"""Tests for multi-database routing (v1.1)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from pyvelm.database_routing import (
    DATABASE_COOKIE,
    DatabaseRegistry,
    DatabaseRoute,
    DEFAULT_DB_KEY,
    get_request_db_key,
    resolve_migrate_dsn,
    resolve_database_key,
)


class DatabaseRegistryTests(unittest.TestCase):
    def test_from_env_csv(self):
        with unittest.mock.patch.dict(
            os.environ,
            {"PYVELM_DATABASES": "tenant_a=postgresql://u:p@localhost/a,tenant_b=postgresql://u:p@localhost/b"},
            clear=False,
        ):
            reg = DatabaseRegistry.from_env()
        self.assertIn("tenant_a", reg.routes)
        self.assertTrue(reg.routes["tenant_a"].dsn.startswith("postgresql+psycopg://"))

    def test_from_env_json(self):
        raw = '[{"key": "demo", "dsn": "postgresql://localhost/demo", "label": "Demo"}]'
        with unittest.mock.patch.dict(os.environ, {"PYVELM_DATABASES": raw}, clear=False):
            reg = DatabaseRegistry.from_env()
        self.assertEqual(reg.routes["demo"].label, "Demo")


class ResolveDatabaseKeyTests(unittest.TestCase):
    def _request(self, *, path="/login", cookies=None, host="localhost"):
        app = MagicMock()
        app.state.database_catalog = DatabaseRegistry(
            routes={"tenant_a": DatabaseRoute("tenant_a", "postgresql://localhost/a")}
        )
        request = MagicMock()
        request.app = app
        request.url.path = path
        request.headers.get.return_value = host
        request.cookies.get.side_effect = lambda k: (cookies or {}).get(k)
        request.scope = {"path": path, "raw_path": path.encode()}
        return request

    def test_cookie_wins(self):
        req = self._request(cookies={DATABASE_COOKIE: "tenant_a"})
        self.assertEqual(resolve_database_key(req), "tenant_a")

    def test_path_prefix_rewrites(self):
        req = self._request(path="/web/db/tenant_a/web/admin")
        self.assertEqual(resolve_database_key(req), "tenant_a")
        self.assertEqual(req.scope["path"], "/web/admin")


class MigrateDsnTests(unittest.TestCase):
    def test_default_uses_pyvelm_dsn(self):
        with unittest.mock.patch.dict(
            os.environ,
            {"PYVELM_DSN": "postgresql://localhost/main"},
            clear=False,
        ):
            dsn = resolve_migrate_dsn(None)
        self.assertIn("postgresql+psycopg://", dsn)

    def test_named_tenant(self):
        with unittest.mock.patch.dict(
            os.environ,
            {
                "PYVELM_DSN": "postgresql://localhost/main",
                "PYVELM_DATABASES": "tenant_a=postgresql://localhost/tenant_a",
            },
            clear=False,
        ):
            dsn = resolve_migrate_dsn("tenant_a")
        self.assertIn("/tenant_a", dsn)


class GetRequestDbKeyTests(unittest.TestCase):
    def test_falls_back_to_default(self):
        app = MagicMock()
        app.state.pool_map = {DEFAULT_DB_KEY: MagicMock()}
        request = MagicMock()
        request.app = app
        request.cookies.get.return_value = None
        request.url.path = "/login"
        request.headers.get.return_value = "localhost"
        request.scope = {"path": "/login"}
        self.assertEqual(get_request_db_key(request), DEFAULT_DB_KEY)


if __name__ == "__main__":
    unittest.main()
