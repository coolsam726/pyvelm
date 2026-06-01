"""Tests for multi-database routing (preview — v1.3+ target)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

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


class DatabaseRegistryMoreTests(unittest.TestCase):
    def test_get_and_items(self):
        route = DatabaseRoute("a", "postgresql://localhost/a", label="A")
        reg = DatabaseRegistry(routes={"a": route})
        self.assertIs(reg.get("a"), route)
        self.assertIsNone(reg.get("missing"))
        self.assertEqual(list(reg.items()), [("a", route)])

    def test_from_env_empty(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PYVELM_DATABASES", None)
            reg = DatabaseRegistry.from_env()
        self.assertEqual(reg.routes, {})

    def test_from_env_skips_invalid_csv_parts(self):
        raw = "badpart,=missing,tenant=postgresql://localhost/t"
        with unittest.mock.patch.dict(os.environ, {"PYVELM_DATABASES": raw}, clear=False):
            reg = DatabaseRegistry.from_env()
        self.assertIn("tenant", reg.routes)
        self.assertNotIn("badpart", reg.routes)


class ResolveDatabaseKeyMoreTests(unittest.TestCase):
    def _request(self, *, path="/", cookies=None, host="localhost"):
        app = MagicMock()
        app.state.database_catalog = DatabaseRegistry(
            routes={
                "tenant_a": DatabaseRoute("tenant_a", "postgresql://localhost/a"),
                "tenant_b": DatabaseRoute("tenant_b", "postgresql://localhost/b", label="B"),
            }
        )
        request = MagicMock()
        request.app = app
        request.url.path = path
        request.headers.get.return_value = host
        request.cookies.get.side_effect = lambda k: (cookies or {}).get(k)
        request.scope = {"path": path, "raw_path": path.encode()}
        return request

    def test_host_subdomain_match(self):
        req = self._request(host="tenant_a.example.com")
        self.assertEqual(resolve_database_key(req), "tenant_a")

    def test_dbfilter_rejects_host(self):
        req = self._request(host="other.example.com")
        with unittest.mock.patch.dict(
            os.environ, {"PYVELM_DBFILTER": r"^tenant_a\."}, clear=False
        ):
            self.assertIsNone(resolve_database_key(req))

    def test_dbfilter_invalid_regex(self):
        req = self._request(host="tenant_a.example.com")
        with unittest.mock.patch.dict(
            os.environ, {"PYVELM_DBFILTER": "[invalid"}, clear=False
        ):
            self.assertIsNone(resolve_database_key(req))

    def test_path_prefix_rewrites_raw_path_bytes(self):
        req = self._request(path="/web/db/tenant_b/admin")
        self.assertEqual(resolve_database_key(req), "tenant_b")
        self.assertEqual(req.scope["path"], "/admin")
        self.assertEqual(req.scope["raw_path"], b"/admin")


class MigrateDsnMoreTests(unittest.TestCase):
    def test_unknown_database_exits(self):
        with unittest.mock.patch.dict(
            os.environ,
            {"PYVELM_DSN": "postgresql://localhost/main"},
            clear=False,
        ):
            with self.assertRaises(SystemExit) as ctx:
                resolve_migrate_dsn("missing")
        self.assertIn("Unknown database", str(ctx.exception))


class RequestDatabaseHelpersTests(unittest.TestCase):
    def test_get_request_database_and_pool(self):
        from pyvelm.database_routing import get_request_database, get_request_pool

        default_db = MagicMock()
        tenant_db = MagicMock()
        app = MagicMock()
        app.state.pool_map = {
            DEFAULT_DB_KEY: default_db,
            "tenant_a": tenant_db,
        }
        app.state.database = default_db
        app.state.pool = MagicMock()

        req = MagicMock()
        req.app = app
        req.cookies.get.return_value = "tenant_a"
        req.url.path = "/"
        req.headers.get.return_value = "localhost"
        req.scope = {"path": "/"}

        self.assertIs(get_request_database(app, req), tenant_db)
        self.assertIs(get_request_pool(app, req), tenant_db.pool)

    def test_get_request_database_fallback(self):
        from pyvelm.database_routing import get_request_database

        default_db = MagicMock()
        app = MagicMock()
        app.state.pool_map = {DEFAULT_DB_KEY: default_db}
        app.state.database = default_db

        req = MagicMock()
        req.app = app
        req.cookies.get.return_value = None
        req.url.path = "/"
        req.headers.get.return_value = "localhost"
        req.scope = {"path": "/"}

        self.assertIs(get_request_database(app, req), default_db)


class ConfigureAppDatabasesTests(unittest.TestCase):
    def test_attach_pool_map_and_catalog(self):
        from pyvelm.database_routing import configure_app_databases, routing_enabled

        app = MagicMock()
        default_db = MagicMock()
        boot_reg = MagicMock()
        with unittest.mock.patch.dict(
            os.environ,
            {
                "PYVELM_DATABASES": "tenant=postgresql://localhost/tenant",
            },
            clear=False,
        ), unittest.mock.patch(
            "pyvelm.database_routing.create_database_from_dsn",
            return_value=MagicMock(),
        ) as create_db:
            configure_app_databases(
                app, default_db, boot_reg, module_roots=["/mods"]
            )
        create_db.assert_called_once()
        self.assertIn(DEFAULT_DB_KEY, app.state.pool_map)
        self.assertIn("tenant", app.state.pool_map)
        self.assertTrue(routing_enabled(app))

    def test_list_selectable_databases(self):
        from pyvelm.database_routing import list_selectable_databases

        app = MagicMock()
        app.state.database_catalog = DatabaseRegistry(
            routes={
                "tenant": DatabaseRoute("tenant", "postgresql://localhost/t", label="Tenant"),
            }
        )
        labels = dict(list_selectable_databases(app))
        self.assertEqual(labels["default"], "Default")
        self.assertEqual(labels["tenant"], "Tenant")


class DatabaseRoutingRegistryTests(unittest.TestCase):
    def test_get_request_registry_uses_cache(self):
        from pyvelm.database_routing import get_request_registry

        cached = MagicMock()
        app = MagicMock()
        app.state.registry_cache = {"tenant": cached}
        app.state.registry = MagicMock()
        app.state.pool_map = {"default": MagicMock(), "tenant": MagicMock()}

        req = MagicMock()
        req.app = app
        req.cookies.get.return_value = "tenant"
        req.url.path = "/"
        req.headers.get.return_value = "localhost"
        req.scope = {"path": "/"}

        self.assertIs(get_request_registry(app, req), cached)

    def test_load_registry_for_connection(self):
        from pyvelm.database_routing import load_registry_for_connection

        conn = MagicMock()
        spec = MagicMock()
        with patch("pyvelm.loader.discover", return_value=[spec]), patch(
            "pyvelm.loader.resolve_order", return_value=[spec]
        ), patch(
            "pyvelm.loader.specs_to_install", return_value=[spec]
        ), patch(
            "pyvelm.loader._load_models"
        ), patch(
            "pyvelm.policies.register_builtin_policies"
        ):
            reg = load_registry_for_connection(conn, ["/mods"])
        self.assertIsNotNone(reg)
        for cls in reg._models.values():
            cls._validate_relations(reg)


class DatabaseSelectorMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_middleware_sets_db_key(self):
        from pyvelm.database_routing import DatabaseSelectorMiddleware

        captured = {}

        async def inner_app(scope, receive, send):
            captured["key"] = scope["state"]["pyvelm_db_key"]

        asgi_app = MagicMock()
        asgi_app.state.pool_map = {DEFAULT_DB_KEY: MagicMock()}
        middleware = DatabaseSelectorMiddleware(inner_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "state": {},
            "app": asgi_app,
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_msg):
            return None

        await middleware(scope, receive, send)
        self.assertEqual(captured["key"], DEFAULT_DB_KEY)


if __name__ == "__main__":
    unittest.main()
