"""Declarative migrations compile on every supported backend."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.migrations import (
    SUPPORTED_ALTERATIONS,
    SUPPORTED_COLUMN_BUILDERS,
    Blueprint,
    Schema,
    Table,
    TableCallback,
)
from pyvelm.migrations.schema import _infer_fk_table
from pyvelm.tests.support.sa_ddl import wire_sa_conn

_DIALECTS = ("postgresql", "sqlite", "mysql", "mssql", "oracle")


class MigrationSchemaCompileTests(unittest.TestCase):
    def _env(self, dialect: str):
        executed: list[str] = []
        conn = MagicMock()
        wire_sa_conn(conn, executed, dialect_name=dialect)
        env = MagicMock()
        env.conn = conn
        return env, executed

    def test_create_table_compiles(self):
        for dialect in _DIALECTS:
            with self.subTest(dialect=dialect):
                env, executed = self._env(dialect)

                def _tbl(t):
                    t.string("name", nullable=False)

                Schema(env).create("demo_model", _tbl)
                self.assertTrue(executed)
                joined = "\n".join(executed).upper()
                self.assertIn("CREATE", joined)
                self.assertIn("DEMO_MODEL", joined.upper().replace('"', ""))

    def test_add_column_compiles(self):
        for dialect in _DIALECTS:
            with self.subTest(dialect=dialect):
                env, executed = self._env(dialect)
                Schema(env).table(
                    "res_users", lambda t: t.string("nickname", nullable=True)
                )
                self.assertTrue(executed)
                self.assertIn("nickname", "\n".join(executed).lower())

    def test_date_and_time_columns_compile(self):
        for dialect in _DIALECTS:
            with self.subTest(dialect=dialect):
                env, executed = self._env(dialect)

                def _alter(t):
                    t.date("publish_on", nullable=True)
                    t.time("standup_at", nullable=True)

                Schema(env).table("demo_note", _alter)
                joined = "\n".join(executed).lower()
                self.assertIn("publish_on", joined)
                self.assertIn("standup_at", joined)

    def test_foreign_constrained_compiles(self):
        for dialect in _DIALECTS:
            with self.subTest(dialect=dialect):
                env, executed = self._env(dialect)

                def _alter(t):
                    t.foreign("group_id").nullable(False).constrained("res_groups")

                Schema(env).table("ir_model_access", _alter)
                joined = "\n".join(executed).lower()
                self.assertIn("group_id", joined)
                self.assertIn("res_groups", joined)
                self.assertIn("foreign key", joined)

    def test_foreign_id_big_compiles(self):
        for dialect in _DIALECTS:
            with self.subTest(dialect=dialect):
                env, executed = self._env(dialect)

                def _alter(t):
                    t.foreignId("ledger_id").cascade().constrained("res_company")

                Schema(env).table("demo_ledger", _alter)
                joined = "\n".join(executed).lower()
                self.assertIn("ledger_id", joined)
                if dialect == "oracle":
                    self.assertIn("number", joined)
                else:
                    self.assertIn("bigint", joined)

    def test_big_integer_column_compiles(self):
        env, executed = self._env("postgresql")
        Schema(env).table("demo", lambda t: t.big("external_id", nullable=True))
        self.assertIn("external_id", "\n".join(executed).lower())

    def test_infer_fk_table_pluralizes(self):
        self.assertEqual(_infer_fk_table("group_id"), "groups")
        self.assertEqual(_infer_fk_table("res_users_id"), "res_users")

    def test_table_alias_is_blueprint(self):
        self.assertIs(Table, Blueprint)

    def test_table_callback_accepts_blueprint(self):
        def _fn(t: Table) -> None:
            t.string("x", nullable=True)

        cb: TableCallback = _fn
        env, _ = self._env("postgresql")
        Schema(env).table("demo", cb)

    def test_supported_columns_registry(self):
        cols = Blueprint.supported_columns()
        self.assertEqual(cols, SUPPORTED_COLUMN_BUILDERS)
        self.assertIn("foreign", cols)
        self.assertIn("big", cols)
        alters = Blueprint.supported_alterations()
        self.assertEqual(alters, SUPPORTED_ALTERATIONS)
        self.assertIn("allow_null", alters)

    def test_infer_fk_table_requires_id_suffix(self):
        with self.assertRaises(ValueError):
            _infer_fk_table("group")

    def test_fluent_foreign_null_and_references(self):
        env, executed = self._env("postgresql")

        def _alter(t):
            t.foreign("partner_id").null().onDelete("SET NULL").references("res_partner")

        Schema(env).table("demo_partner", _alter)
        joined = "\n".join(executed).lower()
        self.assertIn("partner_id", joined)
        self.assertIn("res_partner", joined)

    def test_fluent_foreign_set_null_and_cascade(self):
        env, executed = self._env("postgresql")

        def _alter(t):
            t.foreignId("ledger_id").cascade().constrained("res_company")

        Schema(env).table("demo_ledger2", _alter)
        self.assertIn("ledger_id", "\n".join(executed).lower())

    def test_create_with_boolean_integer_defaults(self):
        env, executed = self._env("postgresql")

        def _tbl(t):
            t.string("code").default("x")
            t.boolean("active").default(True)
            t.integer("qty").default(7)

        Schema(env).create("demo_defaults", _tbl)
        self.assertTrue(executed)

    def test_alter_column_types(self):
        env, executed = self._env("postgresql")

        def _alter(t):
            t.boolean("flag", nullable=True)
            t.float("score", nullable=True)
            t.timestamp("seen_at", nullable=True)

        Schema(env).table("demo_metrics", _alter)
        joined = "\n".join(executed).lower()
        self.assertIn("flag", joined)
        self.assertIn("score", joined)
        self.assertIn("seen_at", joined)

    def test_alter_helpers(self):
        env, executed = self._env("postgresql")

        def _alter(t):
            t.drop_column("legacy")
            t.rename_column("old_name", "new_name")
            t.drop_nullable("code")
            t.allow_null("note")
            t.drop_constraint("demo_metrics_code_key")
            t.foreign_key("country_id", "res_country")

        Schema(env).table("demo_metrics", _alter)
        joined = "\n".join(executed).lower()
        self.assertIn("drop column", joined)
        self.assertIn("rename", joined)
        self.assertIn("not null", joined)
        self.assertIn("foreign key", joined)

    def test_create_only_helpers_raise_on_alter(self):
        cap = __import__(
            "pyvelm.database.dialects", fromlist=["dialect_capabilities"]
        ).dialect_capabilities("postgresql")
        bp = Blueprint("demo", cap, create=False)
        with self.assertRaises(RuntimeError):
            bp.id()
        with self.assertRaises(RuntimeError):
            bp.index("name")
        with self.assertRaises(RuntimeError):
            bp.primary_key("name")

    def test_mssql_create_deferred_foreign_key_and_index(self):
        env, executed = self._env("mssql")

        def _tbl(t):
            t.foreign_id("parent_id", "parent", nullable=True)
            t.index("parent_id")

        Schema(env).create("child_fk", _tbl)
        joined = "\n".join(executed).upper()
        self.assertIn("CREATE", joined)
        self.assertIn("FOREIGN KEY", joined)
        self.assertIn("INDEX", joined)

    def test_add_column_skips_when_exists(self):
        env, executed = self._env("postgresql")
        with patch("pyvelm.database.column_exists", return_value=True):
            Schema(env).table("demo", lambda t: t.string("name", nullable=True))
        self.assertEqual(executed, [])

    def test_schema_data_helpers(self):
        env, executed = self._env("postgresql")
        schema = Schema(env)
        with patch.object(schema, "row_exists", side_effect=[False, True]) as row_exists:
            schema.rename_module("old_mod", "new_mod")
            self.assertEqual(row_exists.call_count, 2)
        schema.copy_column("demo", "dest", "src")
        schema.copy_column_if_dest_empty("demo", "dest", "src")
        schema.update_rows("demo", {"name": "X"}, id=1)
        schema.delete_rows("demo", id=1)
        with patch("pyvelm.database.column_exists", return_value=True):
            self.assertTrue(schema.has_column("demo", "id"))
        with patch.object(schema, "_fetchone", return_value=None):
            self.assertFalse(schema.row_exists("missing", id=99))

    def test_foreign_set_null_and_client_default(self):
        env, executed = self._env("postgresql")

        def _tbl(t):
            t.string("code").default(object())
            t.foreign("owner_id").setNull().constrained("res_users")

        Schema(env).create("demo_owner", _tbl)
        self.assertTrue(executed)

    def test_create_boolean_column(self):
        env, executed = self._env("postgresql")
        Schema(env).create("demo_bool", lambda t: t.boolean("active", nullable=False))
        self.assertIn("active", "\n".join(executed).lower())

    def test_mssql_alter_deferred_foreign_key(self):
        env, executed = self._env("mssql")

        def _alter(t):
            t.foreign_id("company_id", "res_company", nullable=True)

        Schema(env).table("demo_company", _alter)
        self.assertIn("foreign key", "\n".join(executed).lower())

    def test_fetchone_returns_row(self):
        env, executed = self._env("postgresql")
        schema = Schema(env)
        row = MagicMock()
        with patch.object(schema, "_fetchone", return_value=row):
            self.assertEqual(schema._fetchone("t", {"id": 1}), row)

    def test_create_inline_foreign_key_postgresql(self):
        env, executed = self._env("postgresql")

        def _tbl(t):
            t.integer("country_id", nullable=True)
            t.foreign_key("country_id", "res_country")

        Schema(env).create("partner_fk", _tbl)
        joined = "\n".join(executed).upper()
        self.assertIn("FOREIGN KEY", joined)

    def test_create_primary_key_constraint(self):
        env, executed = self._env("postgresql")

        def _tbl(t):
            t.string("code", nullable=False)
            t.primary_key("code")

        Schema(env).create("codes", _tbl)
        self.assertTrue(executed)

    def test_rename_module_deletes_old_when_new_exists(self):
        env, _ = self._env("postgresql")
        schema = Schema(env)
        with patch.object(schema, "row_exists", side_effect=[True, True]):
            with patch.object(schema, "delete_rows") as delete_rows:
                schema.rename_module("old_mod", "new_mod")
        delete_rows.assert_called_once_with("ir_module", name="old_mod")

    def test_where_clause_null_filter(self):
        from pyvelm.migrations.schema import _where_clause
        from sqlalchemy import column as sa_column, table as sa_table

        tbl = sa_table("t", sa_column("name"))
        clause = _where_clause(tbl, {"name": None})
        self.assertIn("IS NULL", str(clause).upper())
