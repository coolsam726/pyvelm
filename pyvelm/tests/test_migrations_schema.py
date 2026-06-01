"""Declarative migrations compile on every supported backend."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

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
