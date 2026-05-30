"""Report execution against a live database."""
from __future__ import annotations

import unittest
from pathlib import Path

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.reports.execute import run_report
from pyvelm.reports.service import execute_report, load_report
from pyvelm.tests.support.db import DatabaseTestCase, install_named_modules, reset_database

_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "modules"
_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [_EXAMPLE_ROOT]


class ReportExecuteIntegrationTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_database(cls.dsn)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        install_named_modules(cls.env, ["admin", "reports", "partners"], _MODULE_ROOTS)
        Country = cls.env["res.country"]
        france = Country.create({"name": "France", "code": "FR"})
        cls.env["res.partner"].create(
            {"name": "Report Alice", "code": "RAL", "country_id": france}
        )

    def test_run_report_detail_with_m2o_label(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [
                {"expr": "name", "label": "Name"},
                {"expr": "country_id", "label": "Country"},
            ],
            "filters": [["name", "ilike", "Report%"]],
            "order": ["name asc"],
        }
        result = run_report(self.env, defn, limit=10)
        self.assertEqual(result.row_count, 1)
        row = result.rows[0]
        self.assertEqual(row["name"], "Report Alice")
        self.assertEqual(row.get("country_id__label"), "France")

    def test_run_report_aggregate(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": ["__count"],
        }
        result = run_report(self.env, defn)
        self.assertTrue(result.is_aggregate)
        self.assertGreaterEqual(result.row_count, 1)

    def test_execute_report_from_ir_report_record(self):
        Report = self.env["ir.report"]
        existing = Report.search([("root_model", "=", "res.partner")], limit=1)
        if existing:
            report = existing[0]
        else:
            import json

            report = Report.create({
                "name": "Partner smoke",
                "root_model": "res.partner",
                "definition": json.dumps({
                    "version": 1,
                    "root": "res.partner",
                    "columns": [{"expr": "name", "label": "Name"}],
                }),
            })
        loaded = load_report(self.env, report.id)
        self.assertIsNotNone(loaded)
        result = execute_report(self.env, loaded, limit=5)
        self.assertGreaterEqual(result.row_count, 1)


if __name__ == "__main__":
    unittest.main()
