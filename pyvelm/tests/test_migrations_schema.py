"""Declarative migrations compile on every supported backend."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm.migrations import Schema
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
