"""Coverage for :mod:`pyvelm.database.sa_alter` and :mod:`pyvelm.database.migration_sql`."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.database.dialects import dialect_capabilities
from pyvelm.database.migration_sql import (
    execute_migration_sql,
    fetchall_migration,
    fetchone_migration,
)
from pyvelm.database.sa_alter import (
    compile_add_foreign_key,
    compile_create_index,
    compile_create_unique,
    compile_drop_column,
    compile_drop_constraint,
    compile_rename_column,
    compile_set_nullable,
    execute_add_foreign_key,
    execute_create_index,
    execute_drop_column,
    execute_drop_constraint,
    execute_rename_column,
    execute_set_column_nullable,
)
from pyvelm.tests.support.sa_ddl import wire_sa_conn

_DIALECTS = ("postgresql", "sqlite", "mysql", "mssql", "oracle")


class SaAlterCompileTests(unittest.TestCase):
    def test_compile_create_index(self):
        cols = ("a", "b")
        self.assertIn(
            "IF NOT EXISTS",
            compile_create_index("ix", "t", cols, dialect_capabilities("postgresql")),
        )
        self.assertIn(
            "IF NOT EXISTS",
            compile_create_index("ix", "t", cols, dialect_capabilities("sqlite")),
        )
        mysql = compile_create_index("ix", "t", cols, dialect_capabilities("mysql"))
        self.assertNotIn("IF NOT EXISTS", mysql)
        self.assertIn("CREATE INDEX", mysql)
        mssql = compile_create_index("ix", "t", cols, dialect_capabilities("mssql"))
        self.assertNotIn("IF NOT EXISTS", mssql)

    def test_compile_create_unique(self):
        cols = ("email",)
        pg = compile_create_unique("uq", "t", cols, dialect_capabilities("postgresql"))
        self.assertIn("UNIQUE INDEX IF NOT EXISTS", pg)
        sqlite = compile_create_unique("uq", "t", cols, dialect_capabilities("sqlite"))
        self.assertIn("IF NOT EXISTS", sqlite)

    def test_compile_drop_column(self):
        pg = compile_drop_column("t", "c", dialect_capabilities("postgresql"))
        self.assertIn("DROP COLUMN IF EXISTS", pg)
        mssql = compile_drop_column("t", "c", dialect_capabilities("mssql"))
        self.assertIn("DROP COLUMN", mssql)
        self.assertNotIn("IF EXISTS", mssql)
        mysql = compile_drop_column("t", "c", dialect_capabilities("mysql"))
        self.assertIn("DROP COLUMN", mysql)
        self.assertNotIn("IF EXISTS", mysql)

    def test_compile_rename_column(self):
        mssql = compile_rename_column("t", "old", "new", dialect_capabilities("mssql"))
        self.assertIn("sp_rename", mssql)
        pg = compile_rename_column("t", "old", "new", dialect_capabilities("postgresql"))
        self.assertIn("RENAME COLUMN", pg)

    def test_compile_drop_constraint(self):
        ora = compile_drop_constraint("t", "c", dialect_capabilities("oracle"))
        self.assertNotIn("IF EXISTS", ora)
        pg = compile_drop_constraint("t", "c", dialect_capabilities("postgresql"))
        self.assertIn("IF EXISTS", pg)

    def test_compile_add_foreign_key(self):
        pg = compile_add_foreign_key(
            "child", "fk", "parent_id", "parent", cap=dialect_capabilities("postgresql")
        )
        self.assertIn("ADD CONSTRAINT", pg)
        mssql = compile_add_foreign_key(
            "child", "fk", "parent_id", "parent", cap=dialect_capabilities("mssql")
        )
        self.assertIn(" ADD ", mssql)
        self.assertNotIn("ADD CONSTRAINT", mssql)

    def test_compile_set_nullable_branches(self):
        for cap_name in ("postgresql", "oracle", "mssql"):
            cap = dialect_capabilities(cap_name)
            allow = compile_set_nullable("t", "c", nullable=True, cap=cap)
            deny = compile_set_nullable(
                "t", "c", nullable=False, cap=cap, type_spec="NVARCHAR(10)"
            )
            self.assertTrue(allow)
            self.assertTrue(deny)


class SaAlterExecuteTests(unittest.TestCase):
    def _conn(self, dialect: str = "postgresql"):
        executed: list[str] = []
        conn = MagicMock()
        wire_sa_conn(conn, executed, dialect_name=dialect)
        return conn, executed

    def test_execute_helpers_emit_sql(self):
        conn, executed = self._conn()
        execute_create_index(conn, "ix", "demo", ("name",))
        execute_drop_column(conn, "demo", "legacy")
        execute_rename_column(conn, "demo", "legacy", "current")
        execute_drop_constraint(conn, "demo", "demo_name_key")
        execute_add_foreign_key(
            conn, "child", "child_parent_fkey", "parent_id", "parent"
        )
        execute_set_column_nullable(conn, "demo", "name", nullable=True)
        self.assertGreaterEqual(len(executed), 5)

    def test_execute_set_column_nullable_mssql_inspects_type(self):
        conn, executed = self._conn("mssql")
        col_info = {"name": "note", "type": "NVARCHAR(255)"}
        with patch("sqlalchemy.inspect") as inspect_mock:
            inspect_mock.return_value.get_columns.return_value = [col_info]
            execute_set_column_nullable(conn, "demo", "note", nullable=False)
        joined = "\n".join(executed).upper()
        self.assertIn("ALTER COLUMN", joined)
        self.assertIn("NOT NULL", joined)


class MigrationSqlTests(unittest.TestCase):
    def test_execute_and_fetch_helpers(self):
        conn = MagicMock()
        row = (1, "x")
        result = MagicMock()
        result.fetchone.return_value = row
        result.fetchall.return_value = [row]
        conn.execute.return_value = result
        with patch(
            "pyvelm.database.migration_sql.execute_sql", return_value=result
        ) as execute_sql:
            self.assertIs(execute_migration_sql(conn, "SELECT 1"), result)
            execute_sql.assert_called_with(conn, "SELECT 1", None)
            self.assertEqual(fetchone_migration(conn, "SELECT 1", (1,)), row)
            self.assertEqual(fetchall_migration(conn, "SELECT 1"), [row])


if __name__ == "__main__":
    unittest.main()
