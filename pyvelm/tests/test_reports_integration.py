"""Report execution against a live Postgres database."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.reports.execute import run_report
from pyvelm.reports.service import execute_report, load_report
from pyvelm.tests.conftest import reset_public_schema

DSN = os.environ.get("PYVELM_DSN")
_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "modules"
_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [_EXAMPLE_ROOT]


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class ReportExecuteIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_public_schema(DSN)
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(_MODULE_ROOTS, cls.env)
        Partner = cls.env["res.partner"]
        Country = cls.env["res.country"]
        france = Country.create({"name": "France", "code": "FR"})
        cls.env["res.partner"].create(
            {"name": "Report Alice", "code": "RAL", "country_id": france}
        )

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

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
