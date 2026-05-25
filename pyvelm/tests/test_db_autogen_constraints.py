"""Tests for schema drift detection in db_autogen (Odoo-style diff)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm.db_autogen import (
    ApplyResult,
    Diff,
    SchemaAlteration,
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


def _mock_env(rows, cls, *, null_check_returns=None):
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

    conn.execute = execute
    env = MagicMock(registry=reg, conn=conn)
    env._executed = executed
    return env


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

