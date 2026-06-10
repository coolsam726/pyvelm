"""Tests for SQLAlchemy Core domain compilation."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Many2many, One2many, Registry
from pyvelm.database import dialect_capabilities
from pyvelm.domain import domain_to_sql
from pyvelm.domain_sa import (
    DomainCompiler,
    _compiled_params,
    _sa_dialect,
    apply_search_pagination,
    clause_to_driver_sql,
    compile_domain_where,
    domain_grouped_select,
    domain_search_select,
)
from pyvelm.fields import Boolean, Integer, Many2one, Text
from pyvelm.paths import M2oHop, O2mHop, Path


def _partner_registry():
    reg = Registry()
    with reg.activate():

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            tag_ids = Many2many("test.tag")

    return reg, Partner


class DomainSACompileTests(unittest.TestCase):
    def test_m2m_path_compiles_to_exists(self):
        reg, Partner = _partner_registry()
        stmt = domain_search_select(
            Partner,
            [("tag_ids.name", "=", "VIP")],
            reg,
        )
        compiled = str(stmt).upper()
        self.assertIn("EXISTS", compiled)

    def test_m2o_chain_compiles_to_join(self):
        reg, Partner = _partner_registry()
        stmt = domain_search_select(
            Partner,
            [("name", "=", "Acme")],
            reg,
        )
        self.assertIn("test_partner", str(stmt))

    def test_oracle_m2o_filter_uses_table_bound_bind_params(self):
        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                name = Char()

            class Rate(BaseModel):
                _name = "res.currency.rate"
                _table = "res_currency_rate"
                currency_id = Many2one("res.currency")
                rate = Integer()

        cap = dialect_capabilities("oracle")
        stmt = domain_search_select(
            Rate,
            [("currency_id", "=", 1)],
            reg,
            capabilities=cap,
            limit=1,
        )
        compiled = stmt.compile(
            dialect=_sa_dialect(cap), compile_kwargs={"render_postcompile": True}
        )
        sql = str(compiled)
        self.assertIn("currency_id_1", sql)
        self.assertNotIn('""res_currency_rate"', sql)
        self.assertIn("currency_id_1", compiled.params)

    def test_oracle_char_order_by_label_uses_varchar_not_clob(self):
        reg = Registry()
        with reg.activate():

            class Menu(BaseModel):
                _name = "ir.ui.menu"
                _table = "ir_ui_menu"
                label = Char(required=True)
                sequence = Integer()
                active = Boolean()

        cap = dialect_capabilities("oracle")
        stmt = domain_search_select(
            Menu,
            [("active", "=", True)],
            reg,
            capabilities=cap,
            order='"sequence" ASC, "label" ASC',
        )
        sql = str(
            stmt.compile(
                dialect=_sa_dialect(cap), compile_kwargs={"render_postcompile": True}
            )
        ).upper()
        self.assertIn("ORDER BY", sql)
        self.assertIn("LABEL", sql)
        self.assertNotIn("CLOB", sql)

    def test_oracle_text_equality_uses_dbms_lob_compare(self):
        reg = Registry()
        with reg.activate():

            class Note(BaseModel):
                _name = "test.note"
                _table = "test_note"
                body = Text()

        cap = dialect_capabilities("oracle")
        stmt = domain_search_select(
            Note,
            [("body", "=", "Admin")],
            reg,
            capabilities=cap,
        )
        self.assertIn("DBMS_LOB.COMPARE", str(stmt).upper())

    def test_text_comparison_operators(self):
        from pyvelm.domain_sa import DomainCompiler, clause_to_driver_sql

        reg, Partner = _partner_registry()
        cap = dialect_capabilities("postgresql")
        compiler = DomainCompiler(Partner, reg, cap)
        col = compiler._col(compiler._base_alias, "name")
        for op, py_op in (("<", "<"), (">", ">"), ("<=", "<="), (">=", ">=")):
            pred = compiler._text_predicate(col, op, "x", Partner._fields["name"])
            sql, _ = clause_to_driver_sql(pred, cap)
            self.assertIn(py_op, sql)
        ne = compiler._text_predicate(col, "!=", "x", Partner._fields["name"])
        sql, _ = clause_to_driver_sql(ne, cap)
        self.assertIn("!=", sql)

    def test_sqlite_ilike_uses_lower_like(self):
        reg, Partner = _partner_registry()
        cap = dialect_capabilities("sqlite")
        stmt = domain_search_select(
            Partner, [("name", "ilike", "%a%")], reg, capabilities=cap
        )
        self.assertIn("lower", str(stmt).lower())

    def test_sa_dialect_mysql_and_mssql(self):
        from pyvelm.domain_sa import _sa_dialect

        self.assertEqual(_sa_dialect(dialect_capabilities("mysql")).name, "mysql")
        self.assertEqual(_sa_dialect(dialect_capabilities("mssql")).name, "mssql")

    def test_apply_search_pagination_adds_order_on_mssql(self):
        from pyvelm.domain_sa import apply_search_pagination, domain_search_select

        reg, Partner = _partner_registry()
        cap = dialect_capabilities("mssql")
        stmt = domain_search_select(Partner, [], reg, capabilities=cap, limit=5)
        paginated = apply_search_pagination(
            stmt, cap, base_table="test_partner", limit=5, offset=0, has_order=False
        )
        self.assertIn("ORDER BY", str(paginated).upper())

    def test_domain_grouped_select_oracle_order(self):
        from pyvelm.domain_sa import domain_grouped_select
        from sqlalchemy import func

        reg, Partner = _partner_registry()
        cap = dialect_capabilities("oracle")
        stmt = domain_grouped_select(
            Partner,
            [],
            reg,
            [func.count()],
            ["name"],
            capabilities=cap,
            limit=10,
        )
        self.assertIn("ORDER BY", str(stmt).upper())

    def test_matches_legacy_sql_shape_for_simple_domain(self):
        reg, Partner = _partner_registry()
        domain = [("name", "ilike", "%vip%")]
        legacy_where, _, _ = domain_to_sql(domain, Partner, reg)
        stmt = domain_search_select(Partner, domain, reg)
        compiled = str(stmt).upper()
        self.assertIn("LOWER", compiled)
        self.assertIn("LIKE", compiled)
        self.assertIn("ILIKE", legacy_where)

    def test_compiler_edge_cases_and_dialect_helpers(self):
        reg, Partner = _partner_registry()
        cap = dialect_capabilities("postgresql")
        compiler = DomainCompiler(Partner, reg, cap)
        col = compiler._col("_missing", "name")
        self.assertIn("name", str(col))

        base_col = compiler._col(compiler._base_alias, "name")
        with self.assertRaises(ValueError):
            compiler._text_predicate(base_col, "??", "x", Partner._fields["name"])

        hop = O2mHop("test.partner", "line_ids", None, "test.line", "partner_id")
        with self.assertRaises(NotImplementedError):
            compiler._emit_m2o_chain([hop])

        self.assertIsNone(compiler._resolve_leaf_field(
            Path("test.partner", [], "test.partner", "id"),
        ))
        bad_path = Path("test.partner", [], "test.partner", "nope")
        with self.assertRaises(ValueError):
            compiler._resolve_leaf_field(bad_path)

        with self.assertRaises(ValueError):
            compiler._compile_tree(("?", ("leaf", ("name", "=", "x"))))
        with patch(
            "pyvelm.domain_sa._parse_polish",
            return_value=(("leaf", ("name", "=", "x")), 0),
        ):
            with self.assertRaises(ValueError):
                compiler.compile_where([("name", "=", "x"), ("name", "=", "y")])

        bad_cap = MagicMock()
        bad_cap.name = "unknown"
        with self.assertRaises(ValueError):
            _sa_dialect(bad_cap)

        compiled = MagicMock()
        compiled.params = {"a": 1, "b": 2}
        compiled.positiontup = ("b", "a")
        self.assertEqual(_compiled_params(compiled), [2, 1])

        from sqlalchemy import func

        stmt = domain_search_select(Partner, [], reg, capabilities=cap)
        paginated = apply_search_pagination(
            stmt, cap, base_table="test_partner", limit=None, offset=2, has_order=True
        )
        self.assertIn("OFFSET", str(paginated).upper())

        grouped = domain_grouped_select(
            Partner,
            [],
            reg,
            [func.count()],
            ["name"],
            capabilities=cap,
            order='"name" ASC',
            offset=1,
            limit=5,
        )
        self.assertIn("ORDER BY", str(grouped).upper())

    def test_exists_for_path_universal_rejects_unsupported_op(self):
        reg, Partner = _partner_registry()
        compiler = DomainCompiler(Partner, reg, dialect_capabilities("postgresql"))
        with self.assertRaises(ValueError):
            compiler._exists_for_path(
                Path("test.partner", [], "test.partner", "name"),
                "child_of",
                1,
                universal=True,
            )

    def test_o2m_nested_path_exists_subquery(self):
        reg = Registry()
        with reg.activate():

            class Line(BaseModel):
                _name = "test.line"
                _table = "test_line"
                partner_id = Many2one("test.partner")
                note = Char()

            class Partner(BaseModel):
                _name = "test.partner"
                _table = "test_partner"
                name = Char()
                line_ids = One2many("test.line", "partner_id")

        Partner = reg["test.partner"]
        cap = dialect_capabilities("postgresql")
        stmt = domain_search_select(
            Partner,
            [("line_ids.note", "=", "urgent")],
            reg,
            capabilities=cap,
        )
        self.assertIn("EXISTS", str(stmt).upper())

    def test_oracle_text_inequality_uses_dbms_lob_compare(self):
        reg = Registry()
        with reg.activate():

            class Note(BaseModel):
                _name = "test.note"
                _table = "test_note"
                body = Text()

        cap = dialect_capabilities("oracle")
        stmt = domain_search_select(
            Note,
            [("body", "!=", "Admin")],
            reg,
            capabilities=cap,
        )
        self.assertIn("DBMS_LOB.COMPARE", str(stmt).upper())

    def test_leaf_col_id_and_missing_field_errors(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "res.country"
                _table = "res_country"
                name = Char()

            class Partner(BaseModel):
                _name = "test.partner"
                _table = "test_partner"
                country_id = Many2one("res.country")

        cap = dialect_capabilities("postgresql")
        compiler = DomainCompiler(reg["test.partner"], reg, cap)
        col, field = compiler._leaf_col("country_id.id")
        self.assertIsNone(field)
        self.assertIn("id", str(col))

        reg2 = Registry()
        with reg2.activate():

            class Country(BaseModel):
                _name = "res.country"
                _table = "res_country"
                name = Char()

            class Partner2(BaseModel):
                _name = "test.partner2"
                _table = "test_partner2"
                country_id = Many2one("res.country")

        compiler2 = DomainCompiler(reg2["test.partner2"], reg2, cap)
        with self.assertRaises(ValueError):
            compiler2._compile_leaf(("country_id.missing_attr", "=", "x"))

    def test_sa_dialect_mysql(self):
        self.assertEqual(_sa_dialect(dialect_capabilities("mysql")).name, "mysql")

    def test_domain_grouped_select_oracle_offset_without_groupby(self):
        from sqlalchemy import func

        reg, Partner = _partner_registry()
        cap = dialect_capabilities("oracle")
        stmt = domain_grouped_select(
            Partner,
            [],
            reg,
            [func.count()],
            None,
            capabilities=cap,
            limit=5,
            offset=2,
        )
        self.assertIn("ORDER BY", str(stmt).upper())

    def test_shared_joins_suppresses_join_sql_fragment(self):
        reg, Partner = _partner_registry()
        joins: list[str] = []
        where, joins_sql = compile_domain_where(
            [("name", "=", "x")],
            Partner,
            reg,
            joins=joins,
        )
        self.assertEqual(joins_sql, "")
        self.assertIsNotNone(where)
