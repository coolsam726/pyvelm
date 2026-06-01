"""Tests for schema drift detection in db_autogen (Odoo-style diff)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from pyvelm.db_autogen import (
    ApplyResult,
    Diff,
    SchemaAlteration,
    _fetch_table_columns_inspector,
    apply_schema_diff,
    compute_diff,
)
from pyvelm.fields import Char, Integer


def _code_field(*, required: bool):
    f = Char(required=required)
    f.name = "code"
    f.column = "code"
    f.is_stored = True
    return f


def _id_field():
    f = Integer(required=False, readonly=True)
    f.name = "id"
    f.column = "id"
    f.is_stored = True
    return f


def _partner_cls(*, required: bool, include_id: bool = False):
    cls = MagicMock()
    cls._name = "res.partner"
    cls._table = "res_partner"
    fields = {"code": _code_field(required=required)}
    if include_id:
        fields["id"] = _id_field()
    cls._fields = fields
    return cls


def _mock_env(rows, cls, *, null_check_returns=None, dialect_name: str = "postgresql"):
    reg = MagicMock()
    reg._model_module = {"res.partner": "partners"}
    reg.__getitem__ = lambda _s, n: cls
    reg.__iter__ = lambda _s: iter(["res.partner"])

    def _cursor(data):
        r = MagicMock()
        r.fetchall.return_value = data
        r.fetchone.return_value = data[0] if data else None
        return r

    conn = MagicMock()
    executed: list[str] = []
    # conn_capabilities() should fall back to dialect_name in these tests.
    conn.capabilities = None
    conn.dialect_name = dialect_name

    def execute(sql, params=None):
        executed.append(sql)
        q = sql.lower()
        if " is null" in q:
            return _cursor(null_check_returns or [])
        if "udt_name" in q or "information_schema.columns" in q:
            return _cursor(rows)
        if "tables" in q:
            return _cursor([(1,)])
        return _cursor([])

    null_scalar = int(null_check_returns[0][0]) if null_check_returns else 0
    from pyvelm.tests.support.sa_ddl import wire_sa_conn

    wire_sa_conn(
        conn,
        executed,
        dialect_name=dialect_name,
        null_scalar=null_scalar,
        base_execute=execute,
    )
    env = MagicMock(registry=reg, conn=conn)
    env._executed = executed
    return env


def _mock_env_dialect(rows, cls, *, dialect_name: str, null_check_returns=None):
    return _mock_env(
        rows, cls, null_check_returns=null_check_returns, dialect_name=dialect_name
    )


class SchemaDiffTests(unittest.TestCase):
    def test_set_not_null_when_db_allows_null(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
        )
        diff = compute_diff(env, "partners")
        self.assertEqual(len(diff.alterations), 1)
        self.assertEqual(diff.alterations[0].kind, "set_not_null")

    def test_type_mismatch_text_vs_integer(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "NO", "int4", "integer")],
            _partner_cls(required=True),
        )
        diff = compute_diff(env, "partners")
        self.assertEqual(len(diff.alterations), 1)
        self.assertEqual(diff.alterations[0].kind, "type")

    def test_no_alteration_when_schema_matches(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "NO", "text", "text")],
            _partner_cls(required=True),
        )
        diff = compute_diff(env, "partners")
        self.assertEqual(diff.alterations, [])

    def test_diff_not_empty_includes_alterations(self):
        d = Diff(alterations=[SchemaAlteration("t", "c", "type", "x")])
        self.assertFalse(d.is_empty)

    def test_id_never_suggests_drop_not_null(self):
        """PK is NOT NULL in Postgres; id must not trigger drop_not_null."""
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "NO", "text", "text")],
            _partner_cls(required=True, include_id=True),
        )
        diff = compute_diff(env, "partners")
        kinds = {a.column: a.kind for a in diff.alterations}
        self.assertNotIn("id", kinds)

    def test_new_table_ddl_emits_single_id_column(self):
        env = _mock_env([], _partner_cls(required=True, include_id=True))
        with patch("pyvelm.db_autogen._fetch_table_columns", return_value=None):
            diff = compute_diff(env, "partners")
        self.assertEqual(len(diff.new_tables), 1)
        _table, columns = diff.new_tables[0]
        id_cols = [c for c in columns if c.name == "id"]
        self.assertEqual(len(id_cols), 1)
        self.assertTrue(id_cols[0].primary_key)


class ApplySchemaDiffTests(unittest.TestCase):
    def test_applies_set_not_null_when_no_null_rows(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
            null_check_returns=[],
        )
        result = apply_schema_diff(env, "partners")
        self.assertEqual(result.set_not_null, 1)
        self.assertEqual(result.skipped_not_null, 0)
        self.assertTrue(
            any("SET NOT NULL" in s and "code" in s for s in env._executed)
        )

    def test_applies_set_not_null_mssql_uses_alter_column_type_not_null(self):
        env = _mock_env_dialect(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
            dialect_name="mssql",
            null_check_returns=[],
        )
        result = apply_schema_diff(env, "partners")
        self.assertEqual(result.set_not_null, 1)
        self.assertTrue(
            any("ALTER COLUMN" in s and "NOT NULL" in s for s in env._executed)
        )
        self.assertFalse(any("SET NOT NULL" in s for s in env._executed))

    def test_applies_set_not_null_oracle_uses_modify(self):
        env = _mock_env_dialect(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
            dialect_name="oracle",
            null_check_returns=[],
        )
        result = apply_schema_diff(env, "partners")
        self.assertEqual(result.set_not_null, 1)
        self.assertTrue(any("MODIFY" in s and "NOT NULL" in s for s in env._executed))

    def test_skips_set_not_null_when_null_rows_exist(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
            null_check_returns=[(1,)],
        )
        result = apply_schema_diff(env, "partners")
        self.assertEqual(result.set_not_null, 0)
        self.assertEqual(result.skipped_not_null, 1)
        self.assertFalse(any("SET NOT NULL" in s for s in env._executed))

    def test_apply_result_summary_includes_not_null(self):
        r = ApplyResult(set_not_null=2, skipped_not_null=1)
        self.assertIn("2 NOT NULL", r.summary())
        self.assertIn("pending", r.summary())

    def test_duplicate_table_on_create_is_swallowed(self):
        """Oracle/MSSQL can raise ORA-00955 when the table already exists.

        ``apply_schema_diff`` must treat a duplicate-object error on CREATE as
        already-applied and continue with column sync instead of crashing.
        """
        env = _mock_env_dialect([], _partner_cls(required=True), dialect_name="oracle")

        def execute(sql, params=None):
            env._executed.append(sql)
            if "CREATE TABLE" in sql.upper():
                raise Exception(
                    "ORA-00955: name is already used by an existing object"
                )
            r = MagicMock()
            r.fetchall.return_value = []
            r.fetchone.return_value = None
            return r

        def sa_execute(stmt, params=None):
            from pyvelm.database.dialects import dialect_capabilities
            from pyvelm.database.sa_ddl import _sqlalchemy_dialect

            sql = str(
                stmt.compile(dialect=_sqlalchemy_dialect(dialect_capabilities("oracle")))
            )
            return execute(sql, params)

        env.conn.execute = execute
        env.conn._sa.execute = sa_execute
        with patch("pyvelm.db_autogen._fetch_table_columns", return_value=None):
            # Must not raise even though the CREATE fails with a duplicate error.
            apply_schema_diff(env, "partners")
        self.assertTrue(
            any("CREATE TABLE" in s.upper() for s in env._executed)
        )

    def test_non_duplicate_create_error_propagates(self):
        env = _mock_env_dialect([], _partner_cls(required=True), dialect_name="oracle")

        def execute(sql, params=None):
            if "CREATE TABLE" in sql.upper():
                raise Exception("ORA-00904: invalid identifier")
            r = MagicMock()
            r.fetchall.return_value = []
            r.fetchone.return_value = None
            return r

        def sa_execute(stmt, params=None):
            from pyvelm.database.dialects import dialect_capabilities
            from pyvelm.database.sa_ddl import _sqlalchemy_dialect

            sql = str(
                stmt.compile(dialect=_sqlalchemy_dialect(dialect_capabilities("oracle")))
            )
            return execute(sql, params)

        env.conn.execute = execute
        env.conn._sa.execute = sa_execute
        with patch("pyvelm.db_autogen._fetch_table_columns", return_value=None):
            with self.assertRaises(Exception):
                apply_schema_diff(env, "partners")

    def test_duplicate_create_re_diffs_and_adds_missing_columns(self):
        """If CREATE TABLE collides (ORA-00955), we must re-diff for columns."""
        env = _mock_env_dialect([], _partner_cls(required=True), dialect_name="oracle")
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.database.sa_ddl import primary_key_column

        cap = dialect_capabilities("oracle")
        code_f = _code_field(required=True)
        first = Diff(new_tables=[("res_partner", [primary_key_column(cap)])])
        second = Diff(
            new_columns=[("res_partner", "code", code_f, True, "text")]
        )
        third = Diff()

        executed: list[str] = []

        def execute(sql, params=None):
            executed.append(sql)
            if "CREATE TABLE" in sql.upper():
                raise Exception("ORA-00955: name is already used by an existing object")
            r = MagicMock()
            r.fetchall.return_value = []
            r.fetchone.return_value = None
            return r

        def sa_execute(stmt, params=None):
            from pyvelm.database.sa_ddl import _sqlalchemy_dialect

            sql = str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))
            return execute(sql, params)

        env.conn.execute = execute
        env.conn._sa.execute = sa_execute
        with patch("pyvelm.db_autogen.compute_diff", side_effect=[first, second, third]):
            with patch("pyvelm.db_autogen._column_exists", return_value=False):
                apply_schema_diff(env, "partners")

        self.assertTrue(any("CREATE TABLE" in s.upper() for s in executed))
        self.assertTrue(
            any('ALTER TABLE "res_partner"' in s and "code" in s for s in executed)
        )


class InspectorEdgeCaseTests(unittest.TestCase):
    def test_fetch_table_columns_inspector_missing_table_returns_none(self):
        from sqlalchemy.exc import NoSuchTableError

        conn = MagicMock()
        conn._sa = MagicMock()
        insp = MagicMock()
        insp.get_table_names.side_effect = NoSuchTableError("base_automation")
        with patch("sqlalchemy.inspect", return_value=insp):
            self.assertIsNone(_fetch_table_columns_inspector(conn, "base_automation"))

