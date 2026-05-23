"""Unit tests for the report builder (no DB required)."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Many2one, Registry
from pyvelm.reports.compile import compile_report, parse_definition
from pyvelm.reports.fields_api import list_exportable_fields, list_fields_level
from pyvelm.reports.format import format_display_value, normalize_column_format
from pyvelm.reports.schema import ReportDefinitionError, validate_definition


def _registry():
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
            country_id = Many2one("res.country")

    return reg


class ReportSchemaTests(unittest.TestCase):
    def test_valid_detail_definition(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [
                {"expr": "name", "label": "Name"},
                {"expr": "country_id.name", "label": "Country"},
            ],
            "order": ["name asc"],
        }
        validate_definition(defn, _registry())

    def test_rejects_private_field(self):
        reg = Registry()
        with reg.activate():

            class Secret(BaseModel):
                _name = "secret.model"
                _table = "secret_model"
                token = Char()

            Secret._fields["token"].private = True

        defn = {
            "version": 1,
            "root": "secret.model",
            "columns": [{"expr": "token", "label": "Token"}],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, reg)

    def test_rejects_unknown_model(self):
        defn = {
            "version": 1,
            "root": "nope.model",
            "columns": [{"expr": "name", "label": "Name"}],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _registry())


class ReportCompileTests(unittest.TestCase):
    def test_compiles_detail_select(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [
                {"expr": "name", "label": "Name"},
                {"expr": "country_id.name", "label": "Country"},
            ],
        }
        compiled = compile_report(defn, _registry(), limit=50)
        self.assertIn("SELECT", compiled.sql)
        self.assertIn('"res_partner"', compiled.sql)
        self.assertIn("LEFT JOIN", compiled.sql)
        self.assertEqual(len(compiled.columns), 2)
        self.assertIn("LIMIT 50", compiled.sql)

    def test_compiles_order_by_non_column_field(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [{"expr": "name", "label": "Name"}],
            "order": ["email desc"],
        }
        compiled = compile_report(defn, _registry())
        self.assertIn("ORDER BY", compiled.sql)
        self.assertIn("email", compiled.sql.lower())

    def test_parameter_filter_skipped_when_empty(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [{"expr": "name", "label": "Name"}],
            "parameters": [{"name": "q", "type": "string", "label": "Q"}],
            "parameter_filters": [["name", "ilike", {"param": "q"}]],
        }
        compiled = compile_report(defn, _registry(), params={})
        self.assertIn("TRUE", compiled.sql)


class ReportFieldsApiTests(unittest.TestCase):
    def test_deep_m2o_path_in_field_picker(self):
        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                symbol = Char(string="Symbol")

            class Company(BaseModel):
                _name = "res.company"
                _table = "res_company"
                currency_id = Many2one("res.currency")

            class Partner(BaseModel):
                _name = "res.partner"
                _table = "res_partner"
                company_id = Many2one("res.company")

        class Env:
            registry = reg

            def check_access(self, model, op):
                return None

        data = list_exportable_fields(Env(), "res.partner")
        exprs = {f["expr"] for f in data["fields"]}
        self.assertIn("company_id.currency_id.symbol", exprs)
        sym = next(f for f in data["fields"] if f["expr"] == "company_id.currency_id.symbol")
        self.assertIn("→", sym["label"])
        self.assertIn("currency", sym["searchText"])

    def test_drill_down_field_levels(self):
        reg = Registry()
        with reg.activate():

            class Currency(BaseModel):
                _name = "res.currency"
                _table = "res_currency"
                _description = "Currency"
                symbol = Char(string="Symbol")

            class Company(BaseModel):
                _name = "res.company"
                _table = "res_company"
                _description = "Company"
                currency_id = Many2one("res.currency", string="Currency")

            class Partner(BaseModel):
                _name = "res.partner"
                _table = "res_partner"
                _description = "Partner"
                company_id = Many2one("res.company", string="Company")

        class Env:
            registry = reg

            def check_access(self, model, op):
                return None

        root = list_fields_level(Env(), "res.partner")
        self.assertEqual(root["model"], "res.partner")
        self.assertEqual(root["breadcrumb"][0]["label"], "Partner")
        company = next(i for i in root["items"] if i["name"] == "company_id")
        self.assertTrue(company["drillable"])
        self.assertEqual(company["kind"], "m2o")

        company_level = list_fields_level(Env(), "res.partner", prefix="company_id")
        self.assertEqual(company_level["model"], "res.company")
        self.assertEqual(len(company_level["breadcrumb"]), 2)
        currency = next(i for i in company_level["items"] if i["name"] == "currency_id")
        self.assertTrue(currency["drillable"])

        currency_level = list_fields_level(Env(), "res.partner", prefix="company_id.currency_id")
        self.assertEqual(currency_level["model"], "res.currency")
        sym = next(i for i in currency_level["items"] if i["name"] == "symbol")
        self.assertEqual(sym["expr"], "company_id.currency_id.symbol")
        self.assertFalse(sym["drillable"])
        self.assertTrue(sym["selectable"])


class ReportFormatTests(unittest.TestCase):
    def test_number_and_currency_format(self):
        self.assertEqual(
            format_display_value(1234.5, fmt={"type": "number", "decimals": 2}),
            "1,234.50",
        )
        self.assertEqual(
            format_display_value(99.9, fmt={"type": "currency", "decimals": 2, "symbol": "€"}),
            "€99.90",
        )
        self.assertEqual(
            format_display_value(42.7, fmt={"type": "integer"}),
            "43",
        )

    def test_column_format_in_definition(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [{
                "expr": "name",
                "label": "Name",
                "format": {"type": "number", "decimals": 1, "align": "right"},
            }],
            "order": ["name asc"],
        }
        validate_definition(defn, _registry())

    def test_rejects_bad_format_type(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [{
                "expr": "name",
                "label": "Name",
                "format": {"type": "nope"},
            }],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, _registry())


class ReportParseTests(unittest.TestCase):
    def test_parse_json_string(self):
        raw = '{"version": 1, "root": "res.partner", "columns": [{"expr": "name", "label": "N"}]}'
        defn = parse_definition(raw)
        self.assertEqual(defn["root"], "res.partner")


if __name__ == "__main__":
    unittest.main()
