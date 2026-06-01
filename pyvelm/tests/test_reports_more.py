"""Additional report builder tests (no DB unless noted)."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Date, Float, Integer, Many2many, Many2one, One2many, Registry
from pyvelm.reports.compile import compile_report, parse_definition
from pyvelm.reports.compile_collections import (
    collection_subquery_expr,
    column_expr_for_path,
    default_subaggregate,
)
from pyvelm.reports.execute import (
    ReportResult,
    _resolve_currency_symbols,
    _resolve_m2o_labels,
    _secured_definition,
    run_report,
)
from pyvelm.reports.export_xlsx import export_csv, export_xlsx
from pyvelm.reports.fields_api import (
    check_definition_access,
    list_active_currencies,
    list_readable_models,
    models_in_definition,
    monetary_currency_path,
)
from pyvelm.reports.format import format_display_value, normalize_column_format
from pyvelm.reports.schema import ReportDefinitionError, validate_definition
from pyvelm.reports.secure import search_read
from pyvelm.reports.service import (
    can_run_report,
    definition_dict,
    execute_report,
    log_run,
    parse_run_params,
    result_to_json,
)
from pyvelm.reports.scheduler import disable_schedule, ensure_daily_cron, run_scheduled_report


def _partner_registry():
    reg = Registry()
    with reg.activate():

        class Country(BaseModel):
            _name = "res.country"
            _table = "res_country"
            name = Char()

        class Partner(BaseModel):
            _name = "res.partner"
            _table = "res_partner"
            name = Char()
            email = Char()
            amount = Float()
            country_id = Many2one("res.country")
            parent_id = Many2one("res.partner")
            child_ids = One2many("res.partner", inverse_name="parent_id")

        class Tag(BaseModel):
            _name = "res.tag"
            _table = "res_tag"
            name = Char()
            partner_ids = Many2many("res.partner")

    return reg


def _detail_defn(**overrides):
    base = {
        "version": 1,
        "root": "res.partner",
        "columns": [{"expr": "name", "label": "Name"}],
    }
    base.update(overrides)
    return base


class ReportSchemaMoreTests(unittest.TestCase):
    def test_rejects_non_object_definition(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition([], _partner_registry())

    def test_rejects_wrong_version(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition({"version": 2, "root": "res.partner", "columns": []}, _partner_registry())

    def test_rejects_duplicate_column_expr(self):
        defn = _detail_defn(columns=[
            {"expr": "name", "label": "A"},
            {"expr": "name", "label": "B"},
        ])
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _partner_registry())

    def test_rejects_groupby_without_measures(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": [],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _partner_registry())

    def test_rejects_unknown_parameter_type(self):
        defn = _detail_defn(parameters=[{"name": "q", "type": "uuid"}])
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _partner_registry())

    def test_rejects_param_filter_unknown_param(self):
        defn = _detail_defn(
            parameters=[{"name": "q", "type": "string"}],
            parameter_filters=[["name", "ilike", {"param": "missing"}]],
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _partner_registry())

    def test_rejects_bad_order_clause(self):
        defn = _detail_defn(order=["name upwards"])
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _partner_registry())

    def test_valid_aggregate_definition(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": ["amount:sum", "__count"],
            "order": ["country_id asc"],
        }
        validate_definition(defn, _partner_registry())


class ReportCompileMoreTests(unittest.TestCase):
    def test_parse_definition_dict_and_empty_errors(self):
        self.assertEqual(parse_definition({"version": 1})["version"], 1)
        with self.assertRaises(ValueError):
            parse_definition("")
        with self.assertRaises(ValueError):
            parse_definition(42)

    def test_parameter_filter_with_value(self):
        defn = _detail_defn(
            parameters=[{"name": "q", "type": "string"}],
            parameter_filters=[["name", "ilike", {"param": "q"}]],
        )
        compiled = compile_report(defn, _partner_registry(), params={"q": "%a%"})
        self.assertNotIn("TRUE", compiled.sql)
        self.assertTrue(compiled.params)

    def test_or_parameter_filters_compacted(self):
        defn = _detail_defn(
            parameters=[{"name": "q", "type": "string"}],
            parameter_filters=[
                ("__or__", "|", [
                    ["name", "ilike", {"param": "q"}],
                    ["email", "ilike", {"param": "q"}],
                ]),
            ],
        )
        compiled = compile_report(defn, _partner_registry(), params={"q": "x"})
        self.assertIn("SELECT", compiled.sql)

    def test_compiles_aggregate_report(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": ["amount:sum", "__count"],
        }
        compiled = compile_report(defn, _partner_registry())
        self.assertTrue(compiled.is_aggregate)
        self.assertIn("GROUP BY", compiled.sql)
        self.assertIn("count(*)", compiled.sql.lower())

    def test_compiles_o2m_subaggregate_column(self):
        defn = _detail_defn(
            columns=[{"expr": "child_ids.name", "label": "Children", "subaggregate": "count"}],
        )
        compiled = compile_report(defn, _partner_registry())
        self.assertIn("SELECT", compiled.sql)
        self.assertEqual(len(compiled.columns), 1)

    def test_currency_column_adds_ccy_key(self):
        defn = _detail_defn(
            columns=[{
                "expr": "amount",
                "label": "Amount",
                "format": {"type": "currency", "currency_source": "field", "currency_field": "currency_id"},
            }],
        )
        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                code = Char()

            class Partner(BaseModel):
                _name = "res.partner"
                _table = "res_partner"
                name = Char()
                amount = Float()
                currency_id = Many2one("res.currency")

        compiled = compile_report(defn, reg)
        self.assertTrue(any(k[0] == "ccy" for k in (compiled.row_key_order or [])))


class ReportExecuteLabelTests(unittest.TestCase):
    def test_resolve_m2o_labels_fallback_to_id(self):
        from pyvelm.reports.compile import ColumnMeta

        env = MagicMock()
        rec = MagicMock()
        rec.id = 3
        rec._fields = {}
        Partner = MagicMock()
        Partner.browse.return_value = [rec]
        env.__getitem__ = lambda _s, k: Partner
        rows = [{"country_id": 3}]
        cols = [
            ColumnMeta(
                key="country_id",
                label="Country",
                expr="country_id",
                comodel="res.country",
                is_m2o=True,
            ),
        ]
        _resolve_m2o_labels(env, cols, rows)
        self.assertEqual(rows[0]["country_id__label"], "3")

    def test_resolve_m2o_labels_skips_empty_ids(self):
        from pyvelm.reports.compile import ColumnMeta

        env = MagicMock()
        rows = [{"country_id": None}]
        cols = [
            ColumnMeta(
                key="country_id",
                label="Country",
                expr="country_id",
                comodel="res.country",
                is_m2o=True,
            ),
        ]
        _resolve_m2o_labels(env, cols, rows)
        env.__getitem__.assert_not_called()

    def test_resolve_m2o_labels(self):
        from pyvelm.reports.compile import ColumnMeta

        env = MagicMock()
        Partner = MagicMock()
        rec = MagicMock()
        rec.id = 7
        rec._fields = {"name": object(), "display_name": object()}
        rec.display_name = "France"
        Partner.browse.return_value = [rec]
        env.__getitem__ = lambda _s, k: Partner if k == "res.country" else MagicMock()
        rows = [{"country_id": 7}]
        cols = [
            ColumnMeta(key="country_id", label="Country", expr="country_id", comodel="res.country", is_m2o=True),
        ]
        _resolve_m2o_labels(env, cols, rows)
        self.assertEqual(rows[0]["country_id__label"], "France")

    def test_resolve_currency_fixed_id(self):
        from pyvelm.reports.compile import ColumnMeta

        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                symbol = Char()
                code = Char()

        env = MagicMock()
        env.registry = reg
        env.check_access = MagicMock()
        rec = MagicMock(id=5, symbol="€", code="EUR")
        Currency = MagicMock()
        Currency.browse.return_value = rec
        env.__getitem__ = lambda _s, k: Currency if k == "res.currency" else reg[k]
        rows = [{"amount": 10}]
        cols = [
            ColumnMeta(
                key="amount",
                label="Amount",
                expr="amount",
                format={"type": "currency", "currency_source": "fixed", "currency_id": 5},
            ),
        ]
        _resolve_currency_symbols(env, cols, rows)
        self.assertEqual(rows[0]["amount__currency_symbol"], "€")

    def test_resolve_currency_from_field(self):
        from pyvelm.reports.compile import ColumnMeta

        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                symbol = Char()
                code = Char()

        env = MagicMock()
        env.registry = reg
        env.check_access = MagicMock()
        rec = MagicMock(id=5, symbol="€", code="EUR")
        Currency = MagicMock()
        Currency.browse.return_value = [rec]
        env.__getitem__ = lambda _s, k: Currency if k == "res.currency" else reg[k]
        rows = [{"amount": 10, "currency_id": 5}]
        cols = [
            ColumnMeta(
                key="amount",
                label="Amount",
                expr="amount",
                format={"type": "currency", "currency_source": "field"},
                currency_id_key="currency_id",
            ),
        ]
        _resolve_currency_symbols(env, cols, rows)
        self.assertEqual(rows[0]["amount__currency_symbol"], "€")

    def test_resolve_currency_skips_without_module_or_permission(self):
        from pyvelm.reports.compile import ColumnMeta

        env = MagicMock()
        env.registry = Registry()
        rows = [{"amount": 1}]
        cols = [
            ColumnMeta(
                key="amount",
                label="Amount",
                expr="amount",
                format={"type": "currency", "currency_source": "fixed", "currency_id": 1},
            ),
        ]
        _resolve_currency_symbols(env, cols, rows)
        env.check_access.side_effect = PermissionError
        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                symbol = Char()

        env.registry = reg
        _resolve_currency_symbols(env, cols, rows)


class ReportCollectionsTests(unittest.TestCase):
    def test_default_subaggregate_by_field_type(self):
        reg = _partner_registry()
        self.assertEqual(default_subaggregate(reg["res.partner"]._fields["amount"]), "sum")
        self.assertEqual(default_subaggregate(reg["res.partner"]._fields["name"]), "string_agg")

    def test_collection_subquery_m2o_string_agg(self):
        reg = _partner_registry()
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.domain_sa import column_element_to_sql
        from pyvelm.paths import parse_path

        cap = dialect_capabilities("postgresql")
        path = parse_path(reg["res.partner"], "child_ids.country_id", reg)
        expr = collection_subquery_expr(
            path, reg["res.partner"], '"res_partner"', reg, "string_agg"
        )
        sql = column_element_to_sql(expr, cap)
        self.assertIn("string_agg", sql.lower())

    def test_collection_subquery_no_hop_raises(self):
        reg = _partner_registry()
        from pyvelm.paths import parse_path

        path = parse_path(reg["res.partner"], "name", reg)
        with self.assertRaises(ValueError):
            collection_subquery_expr(
                path, reg["res.partner"], '"res_partner"', reg, "count"
            )

    def test_collection_subquery_string_agg(self):
        reg = _partner_registry()
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.domain_sa import column_element_to_sql
        from pyvelm.paths import parse_path

        cap = dialect_capabilities("postgresql")
        path = parse_path(reg["res.partner"], "child_ids.name", reg)
        expr = collection_subquery_expr(
            path, reg["res.partner"], '"res_partner"', reg, "string_agg"
        )
        sql = column_element_to_sql(expr, cap)
        self.assertIn("string_agg", sql.lower())

    def test_collection_subquery_unknown_aggregate_raises(self):
        reg = _partner_registry()
        from pyvelm.paths import parse_path
        from pyvelm.reports.compile_collections import _collection_aggregate
        from sqlalchemy import literal_column

        path = parse_path(reg["res.partner"], "child_ids.name", reg)
        with self.assertRaises(ValueError):
            _collection_aggregate(
                "nope",
                leaf_col=literal_column("1"),
                coll_alias="_sqc",
                leaf_cls=reg["res.partner"],
                path=path,
                current_alias="_sqc",
                registry=reg,
            )

    def test_column_expr_requires_compiler(self):
        reg = _partner_registry()
        with self.assertRaises(ValueError):
            column_expr_for_path(
                "name", reg["res.partner"], '"res_partner"', reg, [], {}, [0], None
            )

    def test_collection_subquery_o2m_count(self):
        reg = _partner_registry()
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.domain_sa import column_element_to_sql
        from pyvelm.paths import parse_path

        cap = dialect_capabilities("postgresql")
        path = parse_path(reg["res.partner"], "child_ids.id", reg)
        expr = collection_subquery_expr(
            path, reg["res.partner"], '"res_partner"', reg, "count"
        )
        sql = column_element_to_sql(expr, cap)
        self.assertIn("count(distinct", sql.lower())
        self.assertIn("res_partner", sql)

    def test_column_expr_root_o2m_without_path(self):
        reg = _partner_registry()
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.domain_sa import DomainCompiler, column_element_to_sql

        cap = dialect_capabilities("postgresql")
        compiler = DomainCompiler(reg["res.partner"], reg, cap)
        col_expr, is_m2o, comodel = column_expr_for_path(
            "child_ids",
            reg["res.partner"],
            '"res_partner"',
            reg,
            [],
            {},
            [0],
            "count",
            compiler=compiler,
        )
        sql = column_element_to_sql(col_expr, cap)
        self.assertIn("SELECT", sql)
        self.assertFalse(is_m2o)


class ReportFormatMoreTests(unittest.TestCase):
    def test_normalize_invalid_format_fallback(self):
        fmt = normalize_column_format({"type": "nope", "align": "bogus", "decimals": "x"})
        self.assertEqual(fmt["type"], "text")
        self.assertEqual(fmt["align"], "left")

    def test_display_boolean_and_label(self):
        self.assertEqual(format_display_value(True, fmt={"type": "text"}), "Yes")
        self.assertEqual(format_display_value(False, fmt={"type": "text"}), "No")
        self.assertEqual(format_display_value(1, fmt={"type": "text"}, label_value="X"), "X")
        self.assertEqual(format_display_value(None, fmt={"type": "number"}), "")

    def test_currency_with_symbol_arg(self):
        out = format_display_value(
            10.5,
            fmt={"type": "currency", "decimals": 2},
            currency_symbol="$",
        )
        self.assertEqual(out, "$10.50")

    def test_currency_fixed_and_field_sources(self):
        fmt = normalize_column_format(
            {
                "type": "currency",
                "currency_source": "fixed",
                "currency_id": "5",
                "symbol": " € ",
            }
        )
        self.assertEqual(fmt["currency_source"], "fixed")
        self.assertEqual(fmt["currency_id"], 5)
        self.assertEqual(fmt["symbol"], "€")
        field_fmt = normalize_column_format(
            {"type": "currency", "currency_source": "field", "currency_field": ""}
        )
        self.assertEqual(field_fmt["currency_field"], "currency_id")

    def test_integer_and_number_invalid_values(self):
        self.assertEqual(
            format_display_value("nope", fmt={"type": "integer"}),
            "nope",
        )
        self.assertEqual(
            format_display_value("nope", fmt={"type": "number", "decimals": 2}),
            "nope",
        )
        self.assertEqual(
            format_display_value(12.3, fmt={"type": "number", "decimals": 1}),
            "12.3",
        )


class ReportFieldsApiMoreTests(unittest.TestCase):
    def test_monetary_currency_path(self):
        self.assertEqual(monetary_currency_path("amount", "currency_id"), "currency_id")
        self.assertEqual(
            monetary_currency_path("line_id.amount", "currency_id"),
            "line_id.currency_id",
        )

    def test_models_in_definition_and_check_access(self):
        reg = _partner_registry()
        defn = _detail_defn(columns=[{"expr": "country_id.name", "label": "Country"}])
        models = models_in_definition(defn, reg)
        self.assertIn("res.country", models)

        env = MagicMock()
        env.registry = reg
        check_definition_access(env, defn)
        self.assertGreaterEqual(env.check_access.call_count, 2)

    def test_list_readable_models_filters_acl(self):
        reg = _partner_registry()

        class Env:
            registry = reg
            uid = 1

            def check_access(self, model, op):
                if model == "res.tag":
                    raise PermissionError(model)

        models = list_readable_models(Env())
        names = {m["value"] for m in models}
        self.assertIn("res.partner", names)
        self.assertNotIn("res.tag", names)

    def test_list_active_currencies_empty_without_model(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "res.partner"
                name = Char()

        class Env:
            registry = reg

            def check_access(self, model, op):
                return None

        self.assertEqual(list_active_currencies(Env()), [])


class ReportExportMoreTests(unittest.TestCase):
    def _result(self) -> ReportResult:
        from pyvelm.reports.compile import ColumnMeta

        cols = [
            ColumnMeta(key="name", label="Name", expr="name"),
            ColumnMeta(
                key="amount",
                label="Amount",
                expr="amount",
                format={"type": "currency", "decimals": 2, "symbol": "€"},
            ),
        ]
        rows = [
            {"name": "A", "amount": 1.5, "amount__currency_symbol": "€"},
            {"name": "B", "amount": None},
        ]
        return ReportResult(columns=cols, rows=rows, row_count=2, duration_ms=1)

    def test_export_csv_and_xlsx(self):
        result = self._result()
        csv_text = export_csv(result)
        self.assertIn("Name", csv_text)
        self.assertIn("A", csv_text)
        xlsx = export_xlsx(result, title="Partners")
        self.assertTrue(xlsx[:2] == b"PK")

    def test_export_uses_m2o_label(self):
        from pyvelm.reports.compile import ColumnMeta

        col = ColumnMeta(key="country_id", label="Country", expr="country_id", is_m2o=True)
        result = ReportResult(
            columns=[col],
            rows=[{"country_id": 1, "country_id__label": "France"}],
            row_count=1,
            duration_ms=0,
        )
        self.assertIn("France", export_csv(result))


class ReportServiceTests(unittest.TestCase):
    def test_parse_run_params_types(self):
        defn = {
            "parameters": [
                {"name": "q", "type": "string"},
                {"name": "n", "type": "integer"},
                {"name": "f", "type": "float"},
                {"name": "b", "type": "boolean"},
            ],
        }
        out = parse_run_params(
            defn,
            {"q": "hi", "n": "3", "f": "1.5", "b": "yes"},
        )
        self.assertEqual(out["q"], "hi")
        self.assertEqual(out["n"], 3)
        self.assertAlmostEqual(out["f"], 1.5)
        self.assertTrue(out["b"])

    def test_can_run_report_admin_and_groups(self):
        env = MagicMock()
        env.uid = 1
        report = MagicMock()
        self.assertTrue(can_run_report(env, report))

        env.uid = 2
        empty_groups = MagicMock()
        empty_groups.__bool__.return_value = False
        empty_groups.ids = ()
        report.group_ids = empty_groups
        self.assertTrue(can_run_report(env, report))

        report.group_ids = SimpleNamespace(ids=(10,))
        user = MagicMock()
        user.group_ids = SimpleNamespace(ids=(10, 20))
        env.__getitem__.return_value.browse.return_value = user
        self.assertTrue(can_run_report(env, report))

        user.group_ids = SimpleNamespace(ids=(99,))
        self.assertFalse(can_run_report(env, report))

    def test_definition_dict_and_result_json(self):
        report = SimpleNamespace(
            definition=json.dumps(_detail_defn()),
        )
        self.assertEqual(definition_dict(report)["root"], "res.partner")
        from pyvelm.reports.compile import ColumnMeta

        payload = result_to_json(
            ReportResult(
                columns=[ColumnMeta(key="name", label="Name", expr="name")],
                rows=[],
                row_count=0,
                duration_ms=5,
            )
        )
        self.assertEqual(payload["row_count"], 0)
        self.assertEqual(payload["columns"][0]["key"], "name")

    def test_execute_report_mismatched_root(self):
        env = MagicMock()
        env.registry = _partner_registry()
        report = SimpleNamespace(
            definition=json.dumps(_detail_defn()),
            root_model="res.country",
            row_limit=100,
        )
        with self.assertRaises(ReportDefinitionError):
            execute_report(env, report)

    @patch("pyvelm.reports.service.run_report")
    def test_execute_report_applies_row_limit(self, run_report_mock):
        run_report_mock.return_value = ReportResult(
            columns=[], rows=[], row_count=0, duration_ms=0,
        )
        env = MagicMock()
        env.registry = _partner_registry()
        report = SimpleNamespace(
            definition=json.dumps(_detail_defn()),
            root_model="res.partner",
            row_limit=50,
        )
        execute_report(env, report, limit=200)
        run_report_mock.assert_called_once()
        self.assertEqual(run_report_mock.call_args.kwargs["limit"], 50)

    def test_log_run_skips_without_model(self):
        env = MagicMock()
        env.registry = {}
        log_run(env, MagicMock(), row_count=0, duration_ms=0, fmt="pdf")

    def test_log_run_creates_row(self):
        env = MagicMock()
        env.registry = {"ir.report.run": object(), "res.users": object()}
        Run = MagicMock()
        Users = MagicMock()
        user = MagicMock()
        user.id = 2
        Users.browse.return_value = user

        def getter(name):
            return {"ir.report.run": Run, "res.users": Users}[name]

        env.__getitem__.side_effect = getter
        env.uid = 2
        log_run(env, MagicMock(), row_count=3, duration_ms=9, fmt="csv")
        Run.create.assert_called_once()

    def test_load_report_missing(self):
        from pyvelm.reports.service import load_report

        env = MagicMock()
        Report = MagicMock()
        Report.search.return_value = []
        env.__getitem__.return_value = Report
        self.assertIsNone(load_report(env, 99))


class ReportSchedulerTests(unittest.TestCase):
    @patch("pyvelm.reports.scheduler.log_run")
    @patch("pyvelm.reports.scheduler.execute_report")
    def test_run_scheduled_report_xlsx(self, execute_mock, log_mock):
        from pyvelm.reports.compile import ColumnMeta

        execute_mock.return_value = ReportResult(
            columns=[ColumnMeta(key="name", label="Name", expr="name")],
            rows=[{"name": "A"}],
            row_count=1,
            duration_ms=3,
        )
        Attachment = MagicMock()
        att = MagicMock(id=99)
        Attachment.create.return_value = att
        env = MagicMock()
        env.__getitem__.return_value = Attachment
        report = SimpleNamespace(name="Sales", output_format="xlsx", id=7)
        out = run_scheduled_report(env, report)
        self.assertEqual(out["attachment_id"], 99)
        self.assertEqual(out["format"], "xlsx")
        Attachment.create.assert_called_once()

    @patch("pyvelm.reports.scheduler.log_run")
    @patch("pyvelm.reports.scheduler.execute_report")
    def test_run_scheduled_report_csv_pdf(self, execute_mock, log_mock):
        from pyvelm.reports.compile import ColumnMeta

        execute_mock.return_value = ReportResult(
            columns=[ColumnMeta(key="n", label="N", expr="n")],
            rows=[{"n": "x"}],
            row_count=1,
            duration_ms=1,
        )
        Attachment = MagicMock()
        Attachment.create.return_value = MagicMock(id=1)
        env = MagicMock()
        env.__getitem__.return_value = Attachment
        report = SimpleNamespace(name="R", id=1)

        for fmt in ("csv", "pdf"):
            report.output_format = fmt
            out = run_scheduled_report(env, report)
            self.assertEqual(out["format"], fmt)

    @patch("pyvelm.reports.scheduler.execute_report")
    def test_run_scheduled_report_unknown_format(self, execute_mock):
        from pyvelm.reports.compile import ColumnMeta

        execute_mock.return_value = ReportResult(
            columns=[ColumnMeta(key="n", label="N", expr="n")],
            rows=[],
            row_count=0,
            duration_ms=0,
        )
        env = MagicMock()
        env.__getitem__.return_value = MagicMock()
        with self.assertRaises(ValueError):
            run_scheduled_report(
                env,
                SimpleNamespace(name="X", output_format="doc", id=1),
            )

    def test_ensure_daily_cron_creates_action_and_cron(self):
        Action = MagicMock()
        action = MagicMock()
        Action.create.return_value = action
        Cron = MagicMock()
        cron = MagicMock()
        Cron.create.return_value = cron
        env = MagicMock()
        env.registry = {"ir.cron": object(), "ir.actions.server": object()}

        def getter(name):
            return {"ir.actions.server": Action, "ir.cron": Cron}[name]

        env.__getitem__.side_effect = getter
        report = MagicMock(id=5, name="Weekly", cron_id=None)
        ensure_daily_cron(env, report)
        Action.create.assert_called_once()
        Cron.create.assert_called_once()
        report.write.assert_called_once()

    def test_disable_schedule_deactivates_cron(self):
        cron = MagicMock()
        report = SimpleNamespace(cron_id=cron)
        disable_schedule(MagicMock(), report)
        cron.write.assert_called_once_with({"active": False})

    def test_ensure_daily_cron_updates_existing(self):
        Action = MagicMock()
        Cron = MagicMock()
        action = MagicMock()
        cron = MagicMock()
        cron.action_id = action
        env = MagicMock()
        env.registry = {"ir.cron": object(), "ir.actions.server": object()}

        def getter(name):
            return {"ir.actions.server": Action, "ir.cron": Cron}[name]

        env.__getitem__.side_effect = getter
        report = MagicMock(id=3, name="Daily", cron_id=cron)
        ensure_daily_cron(env, report)
        action.write.assert_called_once()
        cron.write.assert_called_once()
        Action.create.assert_not_called()

    def test_ensure_daily_cron_skips_without_models(self):
        env = MagicMock()
        env.registry = {}
        ensure_daily_cron(env, MagicMock())
        env.__getitem__.assert_not_called()


class ReportSecureTests(unittest.TestCase):
    def test_search_read_with_records(self):
        env = MagicMock()
        rec = MagicMock()
        rec.read.return_value = [{"id": 1, "name": "A"}]
        Model = MagicMock()
        Model.search.return_value = rec
        env.__getitem__.return_value = Model
        rows = search_read(env, "res.partner", fields=["name"])
        self.assertEqual(rows[0]["name"], "A")


class ReportExecuteUnitTests(unittest.TestCase):
    def test_secured_definition_adds_rules_and_company(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "res.partner"
                _table = "res_partner"
                _company_scoped = True
                name = Char()
                company_id = Many2one("res.company")

            class Company(BaseModel):
                _name = "res.company"
                _table = "res_company"
                name = Char()

        env = MagicMock()
        env.registry = reg
        env._acl_bypass = False
        env.company_id = 3
        env.collect_record_rules.return_value = [("active", "=", True)]
        defn = _detail_defn(filters=[])
        secured = _secured_definition(defn, env)
        self.assertIn(("active", "=", True), secured["filters"])
        self.assertIn(("company_id", "=", 3), secured["filters"])

    @patch("pyvelm.reports.execute.compile_report")
    def test_run_report_maps_rows(self, compile_mock):
        from pyvelm.reports.compile import ColumnMeta, CompiledReport

        mock_stmt = MagicMock()
        compile_mock.return_value = CompiledReport(
            sql="SELECT 1",
            params=[],
            columns=[ColumnMeta(key="name", label="Name", expr="name")],
            row_key_order=None,
            stmt=mock_stmt,
        )
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        conn = MagicMock()
        wire_sa_conn(conn, [])
        row_result = MagicMock()
        row_result.fetchall.return_value = [("Alice",)]
        conn._sa.execute = lambda stmt, params=None: row_result
        env = MagicMock()
        env.registry = _partner_registry()
        env.conn = conn
        env.collect_record_rules.return_value = []
        env._acl_bypass = True
        result = run_report(env, _detail_defn())
        self.assertEqual(result.rows[0]["name"], "Alice")
        self.assertEqual(result.row_count, 1)


if __name__ == "__main__":
    unittest.main()
