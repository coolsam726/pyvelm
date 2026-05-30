"""Additional tests for ``pyvelm.db_autogen`` helpers and rendering."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm.db_autogen import (
    ApplyResult,
    Diff,
    SchemaAlteration,
    _field_type_spec,
    _normalize_pg_column,
    _normalize_type_name,
    _q,
    _summary,
    _types_match,
    apply_schema_diff,
    compute_diff,
    count_null_rows,
    migration_filename,
    next_minor_version,
    parse_version,
    render_migration,
)
from pyvelm.fields import Char, Integer
from pyvelm.tests.test_db_autogen_constraints import _mock_env, _partner_cls


class VersionHelperTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_next_minor_version(self):
        self.assertEqual(next_minor_version((1, 0, 5)), (1, 1, 0))
        self.assertEqual(next_minor_version((2,)), (2, 1))

    def test_migration_filename(self):
        self.assertEqual(
            migration_filename((0, 1, 0), (0, 2, 0)),
            "0_1_to_0_2.py",
        )


class QuoteAndSummaryTests(unittest.TestCase):
    def test_q_simple(self):
        self.assertEqual(_q("SELECT 1"), "'SELECT 1'")

    def test_q_with_single_quote(self):
        self.assertIn("'", _q("it's"))

    def test_summary_empty(self):
        diff = Diff()
        self.assertIn("none", _summary(diff))

    def test_summary_mixed(self):
        diff = Diff(
            new_tables=[("t", "CREATE TABLE t")],
            new_columns=[("t", "c", "ALTER", True, "text")],
            alterations=[SchemaAlteration("t", "c", "type", "text→int")],
            orphan_columns=[("t", "old")],
        )
        text = _summary(diff)
        self.assertIn("new table", text)
        self.assertIn("orphan", text)


class RenderMigrationTests(unittest.TestCase):
    def test_render_empty(self):
        diff = Diff()
        body = render_migration(diff, (0, 1, 0), (0, 2, 0))
        self.assertIn("pass", body)
        self.assertIn("nothing to do", body)

    def test_render_new_table_and_columns(self):
        diff = Diff(
            new_tables=[("res_partner", 'CREATE TABLE "res_partner" ()')],
            new_columns=[
                (
                    "res_partner",
                    "code",
                    'ALTER TABLE "res_partner" ADD COLUMN "code" text',
                    True,
                    "text",
                )
            ],
            alterations=[
                SchemaAlteration("res_partner", "code", "set_not_null", "required"),
                SchemaAlteration("res_partner", "name", "drop_not_null", "optional"),
                SchemaAlteration("res_partner", "qty", "type", "int4→text"),
            ],
            orphan_columns=[("res_partner", "legacy")],
        )
        body = render_migration(diff, (0, 1, 0), (0, 2, 0))
        self.assertIn("CREATE TABLE", body)
        self.assertIn("ADD COLUMN", body)
        self.assertIn("SET NOT NULL", body)
        self.assertIn("DROP NOT NULL", body)
        self.assertIn("orphan", body.lower())


class ApplyResultTests(unittest.TestCase):
    def test_is_empty_and_summary(self):
        r = ApplyResult()
        self.assertTrue(r.is_empty)
        self.assertEqual(r.summary(), "schema unchanged")

    def test_summary_with_changes(self):
        r = ApplyResult(new_tables=1, new_columns=2, set_not_null=1)
        self.assertIn("table", r.summary())


class SchemaAlterationCliLineTests(unittest.TestCase):
    def test_cli_line_kinds(self):
        self.assertIn("required", SchemaAlteration("t", "c", "set_not_null", "x").cli_line())
        self.assertIn("optional", SchemaAlteration("t", "c", "drop_not_null", "x").cli_line())
        self.assertIn("type mismatch", SchemaAlteration("t", "c", "type", "x").cli_line())
        self.assertIn("other", SchemaAlteration("t", "c", "other", "x").cli_line())


class TypeHelperTests(unittest.TestCase):
    def test_normalize_and_match(self):
        self.assertEqual(_normalize_type_name("INTEGER"), "integer")
        self.assertEqual(_normalize_pg_column("int4", "integer"), "integer")
        self.assertTrue(_types_match("integer", "integer"))
        self.assertFalse(_types_match("integer", "text"))

    def test_field_type_spec(self):
        f = Char()
        self.assertEqual(_field_type_spec(f), "text")


class ComputeDiffNewTableTests(unittest.TestCase):
    def test_new_table_when_missing_in_db(self):
        cls = MagicMock()
        cls._name = "res.partner"
        cls._table = "res_partner"
        f = Char()
        f.name = "name"
        f.column = "name"
        f.is_stored = True
        cls._fields = {"name": f}

        reg = MagicMock()
        reg._model_module = {"res.partner": "partners"}
        reg.__getitem__ = lambda _s, n: cls
        reg.__iter__ = lambda _s: iter(["res.partner"])

        conn = MagicMock()

        def execute(sql, params=None):
            q = sql.lower()
            r = MagicMock()
            if "information_schema.tables" in q:
                r.fetchone.return_value = None
                return r
            if "information_schema.columns" in q:
                r.fetchall.return_value = []
                return r
            r.fetchall.return_value = []
            r.fetchone.return_value = None
            return r

        conn.execute = execute
        env = MagicMock(registry=reg, conn=conn)
        diff = compute_diff(env, "partners")
        self.assertTrue(diff.new_tables)
        self.assertTrue(any(t == "res_partner" for t, _ in diff.new_tables))


class ApplySchemaDiffDropNotNullTests(unittest.TestCase):
    def test_drop_not_null_applied(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "NO", "text", "text")],
            _partner_cls(required=False),
        )
        diff = Diff(
            alterations=[
                SchemaAlteration("res_partner", "code", "drop_not_null", "optional"),
            ],
        )
        from pyvelm.db_autogen import _apply_nullability

        r = ApplyResult()
        _apply_nullability(env, diff, r)
        self.assertEqual(r.drop_not_null, 1)

    def test_count_null_rows(self):
        env = _mock_env([], _partner_cls(required=True))
        env.conn.execute = MagicMock(
            return_value=MagicMock(fetchone=MagicMock(return_value=(3,)))
        )
        self.assertEqual(count_null_rows(env, "res_partner", "code"), 3)

    def test_set_not_null_skipped_when_nulls_exist(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "YES", "text", "text")],
            _partner_cls(required=True),
            null_check_returns=[(1,)],
        )
        from pyvelm.db_autogen import _apply_nullability

        diff = Diff(
            alterations=[
                SchemaAlteration("res_partner", "code", "set_not_null", "tighten"),
            ],
        )
        r = ApplyResult()
        _apply_nullability(env, diff, r)
        self.assertEqual(r.skipped_not_null, 1)
        self.assertIn("res_partner.code", r.skipped_not_null_cols[0])


class ComputeDiffOrphanAndTypeTests(unittest.TestCase):
    def test_orphan_column_and_type_mismatch(self):
        env = _mock_env(
            [
                ("id", "NO", "int4", "integer"),
                ("code", "YES", "text", "text"),
                ("legacy", "YES", "text", "text"),
            ],
            _partner_cls(required=True),
        )
        diff = compute_diff(env, "partners")
        self.assertTrue(any(c == "legacy" for _, c in diff.orphan_columns))
        self.assertTrue(any(a.kind == "set_not_null" for a in diff.alterations))


class ApplySchemaDiffIntegrationTests(unittest.TestCase):
    def test_apply_empty_diff(self):
        env = _mock_env(
            [("id", "NO", "int4", "integer"), ("code", "NO", "text", "text")],
            _partner_cls(required=True),
        )
        result = apply_schema_diff(env, "partners")
        self.assertTrue(result.is_empty)


if __name__ == "__main__":
    unittest.main()
