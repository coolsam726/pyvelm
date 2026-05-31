"""Tests for pyvelm.database (v1 portability layer)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pyvelm.database import (
    ConnectionAdapter,
    Database,
    app_dsn_from_env,
    create_database_from_dsn,
    dialect_capabilities,
    ilike_sql,
    is_serverless_runtime,
    migration_supported,
    normalize_dsn,
    resolve_sqlite_dsn_for_runtime,
    serial_primary_key,
    sqlite_file_path,
    test_dsn_from_env as get_test_dsn_from_env,
    to_psycopg_dsn,
)
from pyvelm.tests.support.db import _assert_safe_reset_dsn


class NormalizeDsnTests(unittest.TestCase):
    def test_postgresql_legacy(self):
        self.assertEqual(
            normalize_dsn("postgresql://u:p@localhost/db"),
            "postgresql+psycopg://u:p@localhost/db",
        )

    def test_postgres_shorthand(self):
        self.assertTrue(
            normalize_dsn("postgres://localhost/x").startswith("postgresql+psycopg://")
        )

    def test_to_psycopg_dsn(self):
        self.assertEqual(
            to_psycopg_dsn("postgresql+psycopg://u:p@localhost/db"),
            "postgresql://u:p@localhost/db",
        )


class DialectCapabilitiesTests(unittest.TestCase):
    def test_sqlite_ilike_disabled(self):
        cap = dialect_capabilities("sqlite")
        self.assertFalse(cap.supports_ilike)
        self.assertIn("LOWER", ilike_sql('"t"."name"', cap))

    def test_postgres_ilike(self):
        cap = dialect_capabilities("postgresql")
        self.assertIn("ILIKE", ilike_sql('"t"."name"', cap))


class SqliteDatabaseTests(unittest.TestCase):
    def test_create_table_and_insert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            dsn = f"sqlite:///{path}"
            db = create_database_from_dsn(dsn, pool_size=1)
            with db.connect() as conn:
                conn.execute(
                    'CREATE TABLE IF NOT EXISTS "demo" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" text)'
                )
                conn.execute('INSERT INTO "demo" ("name") VALUES (%s)', ["alpha"])
                row = conn.execute('SELECT "name" FROM "demo" WHERE "id" = %s', [1]).fetchone()
            db.dispose()
        self.assertEqual(row, ("alpha",))

    def test_serial_primary_key_sqlite(self):
        cap = dialect_capabilities("sqlite")
        self.assertIn("AUTOINCREMENT", serial_primary_key(cap))


class MigrationSupportedTests(unittest.TestCase):
    def test_skips_postgres_only_on_sqlite(self):
        cap = dialect_capabilities("sqlite")
        conn = mock.Mock()
        conn.dialect_name = "sqlite"
        self.assertFalse(
            migration_supported(conn, ("postgresql",))
        )


class ServerlessSqliteTests(unittest.TestCase):
    def test_is_serverless_detects_vercel(self):
        with mock.patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            self.assertTrue(is_serverless_runtime())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_serverless_runtime())

    def test_resolve_copies_readonly_bundled_db_to_tmp(self):
        import stat
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.db"
            seed.write_bytes(b"sqlite-seed-bytes")
            seed.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            dsn = f"sqlite:///{seed}"
            with mock.patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
                resolved = resolve_sqlite_dsn_for_runtime(dsn)
            dest = sqlite_file_path(resolved)
            self.assertIsNotNone(dest)
            assert dest is not None
            self.assertTrue(dest.startswith("/tmp/pyvelm-"))
            self.assertTrue(Path(dest).is_file())
            self.assertEqual(Path(dest).read_bytes(), b"sqlite-seed-bytes")
            Path(dest).unlink(missing_ok=True)

    def test_resolve_honors_pyvelm_sqlite_path(self):
        with mock.patch.dict(
            os.environ,
            {"VERCEL": "1", "PYVELM_SQLITE_PATH": "/tmp/custom-pyvelm.db"},
            clear=True,
        ):
            out = resolve_sqlite_dsn_for_runtime("sqlite:///var/readonly.db")
        self.assertEqual(out, "sqlite:////tmp/custom-pyvelm.db")


class TestDsnEnvTests(unittest.TestCase):
    def test_test_dsn_from_env(self):
        with mock.patch.dict(
            os.environ,
            {"PYVELM_DSN_TEST": "postgresql://localhost/pyvelm_test"},
            clear=True,
        ):
            self.assertEqual(
                get_test_dsn_from_env(),
                "postgresql+psycopg://localhost/pyvelm_test",
            )

    def test_test_dsn_ignores_app_dsn(self):
        with mock.patch.dict(
            os.environ,
            {
                "PYVELM_DSN": "postgresql://localhost/pyvelm_dev",
                "PYVELM_DSN_TEST": "postgresql://localhost/pyvelm_test",
            },
            clear=True,
        ):
            self.assertNotEqual(get_test_dsn_from_env(), app_dsn_from_env())

    def test_reset_refuses_app_dsn(self):
        with mock.patch.dict(
            os.environ,
            {"PYVELM_DSN": "postgresql://localhost/pyvelm_dev"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Refusing to reset"):
                _assert_safe_reset_dsn("postgresql://localhost/pyvelm_dev")

    def test_reset_allows_test_dsn_when_app_differs(self):
        with mock.patch.dict(
            os.environ,
            {
                "PYVELM_DSN": "postgresql://localhost/pyvelm_dev",
                "PYVELM_DSN_TEST": "postgresql://localhost/pyvelm_test",
            },
            clear=True,
        ):
            _assert_safe_reset_dsn("postgresql://localhost/pyvelm_test")

    def test_nuke_dsn_prefers_nuke_env(self):
        from pyvelm.database import nuke_dsn_from_env

        with mock.patch.dict(
            os.environ,
            {
                "PYVELM_DSN": "postgresql://localhost/pooler",
                "PYVELM_NUKE_DSN": "postgresql://localhost/direct",
            },
            clear=True,
        ):
            self.assertEqual(
                nuke_dsn_from_env(),
                "postgresql+psycopg://localhost/direct",
            )

    def test_transaction_pooler_detects_6543(self):
        from pyvelm.database import is_transaction_pooler_dsn

        self.assertTrue(
            is_transaction_pooler_dsn(
                "postgresql://u:p@aws.pooler.supabase.com:6543/postgres"
            )
        )
        self.assertFalse(
            is_transaction_pooler_dsn(
                "postgresql://u:p@aws.pooler.supabase.com:5432/postgres"
            )
        )

    def test_supabase_direct_host(self):
        from pyvelm.database import is_supabase_direct_host

        self.assertTrue(
            is_supabase_direct_host(
                "postgresql://postgres:pw@db.abcdef.supabase.co:5432/postgres"
            )
        )
        self.assertFalse(
            is_supabase_direct_host(
                "postgresql://postgres:pw@aws.pooler.supabase.com:5432/postgres"
            )
        )

    def test_terminate_other_backends_swallows_errors(self):
        from pyvelm.database import terminate_other_backends

        conn = mock.MagicMock()
        conn.capabilities.name = "postgresql"
        conn.execute.side_effect = RuntimeError("permission denied")
        terminate_other_backends(conn)  # must not raise


class DevelopmentDbDisplayTests(unittest.TestCase):
    def test_hidden_in_production(self):
        from pyvelm.render import development_db_display

        with mock.patch.dict(
            os.environ,
            {"PYVELM_ENV": "production", "PYVELM_DSN": "sqlite:///tmp/x.db"},
            clear=True,
        ):
            self.assertIsNone(development_db_display())

    def test_shows_redacted_dsn_in_development(self):
        from pyvelm.render import development_db_display

        with mock.patch.dict(
            os.environ,
            {
                "PYVELM_ENV": "development",
                "PYVELM_DSN": "postgresql://user:secret@localhost:5432/pyvelm",
            },
            clear=True,
        ):
            shown = development_db_display()
        self.assertIn("postgresql", shown)
        self.assertIn("user:***", shown)
        self.assertNotIn("secret", shown)

    def test_missing_dsn_in_development(self):
        from pyvelm.render import development_db_display

        with mock.patch.dict(os.environ, {"PYVELM_ENV": "development"}, clear=True):
            shown = development_db_display()
        self.assertIn("PYVELM_DSN not set", shown)


if __name__ == "__main__":
    unittest.main()
