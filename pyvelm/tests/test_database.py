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
    migration_supported,
    normalize_dsn,
    serial_primary_key,
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


if __name__ == "__main__":
    unittest.main()
