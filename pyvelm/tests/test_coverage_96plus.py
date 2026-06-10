"""Targeted tests to raise per-module coverage above 96%."""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Registry
from pyvelm.branding import (
    document_logo_height_px,
    document_logo_style,
    logo_max_width_px,
)
from pyvelm.database import _bind_params
from pyvelm.database.dialects import dialect_capabilities
from pyvelm.database.dsn import normalize_dsn, to_psycopg_dsn
from pyvelm.database.postgres_admin import (
    prepare_postgres_schema_drop,
    release_postgres_schema_drop_lock,
    terminate_other_backends,
)
from pyvelm.file_icons import file_icon_key
from pyvelm.home import home_url, login_url
from pyvelm.reports.format import normalize_column_format
from pyvelm.runtime import cookie_options, get_runtime_env, normalize_env
from pyvelm.timestamps import (
    apply_timestamp_vals,
    install_timestamps,
    timestamp_columns,
    uses_timestamps,
)


class QuickWinCoverageTests(unittest.TestCase):
    def test_file_icon_media_prefixes(self):
        self.assertEqual(file_icon_key("text/plain"), "text")
        self.assertEqual(file_icon_key("audio/mpeg"), "audio")
        self.assertEqual(file_icon_key("video/webm"), "video")

    def test_home_empty_and_relative_url(self):
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "  "}):
            self.assertEqual(home_url(), "/web/admin")
        with patch.dict(os.environ, {"PYVELM_HOME_URL": "web/admin"}):
            self.assertEqual(home_url(), "/web/admin")

    def test_login_url_avoids_login_loop(self):
        self.assertEqual(login_url(next_path="/login"), "/login")

    def test_runtime_invalid_env(self):
        with self.assertRaises(ValueError):
            normalize_env("staging")
        self.assertTrue(cookie_options(env="production")["secure"])

    def test_report_format_currency_fallbacks(self):
        fmt = normalize_column_format({
            "type": "currency",
            "currency_source": "bogus",
            "currency_id": "bad",
        })
        self.assertEqual(fmt["currency_source"], "field")
        self.assertNotIn("currency_id", fmt)

    def test_report_format_fixed_currency_bad_id(self):
        fmt = normalize_column_format({
            "type": "currency",
            "currency_source": "fixed",
            "currency_id": "not-an-int",
        })
        self.assertEqual(fmt["currency_source"], "fixed")
        self.assertNotIn("currency_id", fmt)

    def test_branding_invalid_ints(self):
        with patch.dict(os.environ, {"PYVELM_HEADER_LOGO_HEIGHT": "abc"}, clear=False):
            from pyvelm.branding import brand_dict

            self.assertGreater(brand_dict(None)["header_logo_height"], 0)
        self.assertEqual(document_logo_height_px("x"), 56)
        self.assertEqual(document_logo_height_px(0), 56)
        self.assertIn("max-width", document_logo_style(40))
        self.assertGreater(logo_max_width_px(40), 40)

    def test_timestamps_disabled_paths(self):
        reg = Registry()
        with reg.activate():

            class Legacy(BaseModel):
                _name = "test.legacy.ts"
                _timestamps = False
                title = Char()

        self.assertEqual(timestamp_columns(Legacy), ())
        install_timestamps(Legacy)
        vals = apply_timestamp_vals(Legacy, {"title": "x"}, updating=False)
        self.assertEqual(vals, {"title": "x"})
        self.assertFalse(uses_timestamps(Legacy))

    def test_database_bind_params(self):
        cap = dialect_capabilities("postgresql")
        self.assertEqual(_bind_params((1, 2), cap), (1, 2))

    def test_dsn_errors(self):
        with self.assertRaises(ValueError):
            normalize_dsn("")
        with self.assertRaises(ValueError):
            to_psycopg_dsn("sqlite:///tmp/x.db")


class PostgresAdminTests(unittest.TestCase):
    def test_non_postgres_noop(self):
        conn = MagicMock()
        conn.capabilities = dialect_capabilities("sqlite")
        terminate_other_backends(conn)
        prepare_postgres_schema_drop(conn, "public")
        release_postgres_schema_drop_lock(conn, "public")
        conn.execute.assert_not_called()

    def test_postgres_prepare_non_serverless(self):
        conn = MagicMock()
        conn.capabilities = dialect_capabilities("postgresql")
        with patch(
            "pyvelm.database.postgres_admin._uses_serverless_schema_wipe",
            return_value=False,
        ):
            prepare_postgres_schema_drop(conn, "public")
        self.assertTrue(conn.execute.called)

    def test_postgres_release_lock_serverless(self):
        conn = MagicMock()
        conn.capabilities = dialect_capabilities("postgresql")
        with patch(
            "pyvelm.database.postgres_admin._uses_serverless_schema_wipe",
            return_value=True,
        ):
            release_postgres_schema_drop_lock(conn, "custom")
        conn.execute.assert_called()


class RequestEnvCoverageTests(unittest.TestCase):
    def test_invalid_company_cookie_ignored(self):
        from pyvelm.env import Environment
        from pyvelm.request_env import COMPANY_COOKIE, apply_request_scope

        env = Environment(MagicMock(), registry=MagicMock(), uid=None).with_company(1)
        request = SimpleNamespace(
            cookies={COMPANY_COOKIE: "not-a-number"},
            headers={},
        )
        scoped = apply_request_scope(
            env,
            request,
            resolve_session=lambda _e, _t: None,
            resolve_basic=lambda _e, _h: None,
        )
        self.assertEqual(scoped.company_id, 1)


class ReportSchemaExtraTests(unittest.TestCase):
    def setUp(self):
        from pyvelm.tests.test_coverage_gaps import _partner_registry

        self.reg = _partner_registry()

    def _base(self, **extra):
        d = {
            "version": 1,
            "root": "res.partner",
            "columns": [{"expr": "name", "label": "Name"}],
        }
        d.update(extra)
        return d

    def test_aggregate_order_and_format_edges(self):
        from pyvelm.reports.schema import ReportDefinitionError, validate_definition

        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": ["__count"],
            "order": ["bogus asc"],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, self.reg)

        bad_fmt = self._base(
            columns=[{
                "expr": "name",
                "label": "N",
                "format": {"decimals": "x", "symbol": 1},
            }],
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(bad_fmt, self.reg)

        currency_fmt = self._base(
            columns=[{
                "expr": "amount",
                "label": "A",
                "format": {
                    "type": "currency",
                    "currency_field": 9,
                },
            }],
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(currency_fmt, self.reg)

    def test_domain_and_param_refs(self):
        from pyvelm.reports.schema import ReportDefinitionError, validate_definition

        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(filters=[("nope", "=", "x")]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    parameters=[{"name": "q", "type": "string"}],
                    parameter_filters=[["name", "=", {"param": "missing"}]],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(order=[1]), self.reg)

    def test_non_stored_groupby_raises(self):
        from pyvelm.reports.schema import ReportDefinitionError, validate_definition

        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["label"],
                    "measures": ["__count"],
                },
                self.reg,
            )


class ReportCompileExtraTests(unittest.TestCase):
    def setUp(self):
        from pyvelm.tests.test_coverage_gaps import _partner_registry

        self.reg = _partner_registry()

    def _detail(self, **extra):
        d = {
            "version": 1,
            "root": "res.partner",
            "columns": [{"expr": "name", "label": "Name"}],
        }
        d.update(extra)
        return d

    def test_substitute_and_compact_domain_helpers(self):
        from pyvelm.reports.compile import _compact_domain, _substitute_param_leaf

        self.assertIsNone(
            _substitute_param_leaf(
                ("__or__", "|", [["name", "=", {"param": "q"}]]),
                {},
            )
        )
        self.assertIsNone(
            _substitute_param_leaf(["name", "=", {"param": "q"}], {"q": ""}),
        )
        substituted = _substitute_param_leaf(
            ["name", "=", "x", {"case_insensitive": True}],
            {},
        )
        self.assertEqual(len(substituted), 4)
        compacted = _compact_domain([None, ("name", "=", "a")])
        self.assertEqual(compacted, [("name", "=", "a")])

    def test_aggregate_trunc_and_measure_defaults(self):
        from pyvelm.database.dialects import dialect_capabilities
        from pyvelm.reports.compile import compile_report

        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [],
            "groupby": ["create_date:month"],
            "measures": ["amount", "amount:avg"],
            "order": ["create_date:month desc", "amount desc"],
        }
        compiled = compile_report(
            {**defn, "measures": ["amount", "amount:avg", "__count"]},
            self.reg,
        )
        self.assertIn("date_trunc", compiled.sql.lower())
        self.assertTrue(compiled.is_aggregate)

        sqlite_cap = dialect_capabilities("sqlite")
        compiled_sqlite = compile_report(defn, self.reg, capabilities=sqlite_cap)
        self.assertIn("date_trunc", compiled_sqlite.sql.lower())

        with self.assertRaises(ValueError):
            compile_report(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["create_date:bad"],
                    "measures": ["__count"],
                },
                self.reg,
            )
        with self.assertRaises(ValueError):
            compile_report(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["country_id"],
                    "measures": ["amount:median"],
                },
                self.reg,
            )

    @patch("pyvelm.reports.compile.column_expr_for_path")
    def test_detail_order_skips_invalid_extra_field(self, col_expr_mock):
        from pyvelm.reports.compile import compile_report
        from pyvelm.reports.compile_collections import column_expr_for_path as real_col_expr

        def side_effect(expr, *args, **kwargs):
            if expr == "email":
                raise ValueError("bad order path")
            return real_col_expr(expr, *args, **kwargs)

        col_expr_mock.side_effect = side_effect
        defn = self._detail(
            columns=[{"expr": "name", "label": "Name"}],
            order=["name asc", "email desc"],
        )
        compiled = compile_report(defn, self.reg)
        self.assertIn("ORDER BY", compiled.sql)
        self.assertNotIn("email", compiled.sql.lower())

    def test_detail_order_and_currency_fallback(self):
        from pyvelm.reports.compile import ColumnMeta, compile_report

        defn = self._detail(
            columns=[{"expr": "name", "label": "Name"}],
            order=["name asc", "email desc"],
        )
        compiled = compile_report(defn, self.reg)
        self.assertIn("ORDER BY", compiled.sql)

        bad_ccy = self._detail(
            columns=[{
                "expr": "amount_m",
                "label": "Amt",
                "format": {
                    "type": "currency",
                    "currency_source": "field",
                    "currency_field": "missing_currency",
                },
            }],
        )
        compiled_bad = compile_report(bad_ccy, self.reg)
        self.assertIsNone(compiled_bad.columns[0].currency_id_key)

        meta = ColumnMeta(key="x", label="X", expr="x", format={"type": "text"})
        self.assertEqual(meta.format_dict()["type"], "text")

    def test_parse_definition_none(self):
        from pyvelm.reports.compile import parse_definition

        with self.assertRaises(ValueError):
            parse_definition(None)


class FieldsApiExtraTests(unittest.TestCase):
    def test_list_active_currencies_without_model(self):
        from pyvelm.reports.fields_api import list_active_currencies

        env = MagicMock(registry={})

        class E:
            registry = {}

            def check_access(self, *a):
                pass

        self.assertEqual(list_active_currencies(E()), [])

    def test_check_definition_access_raises(self):
        from pyvelm.reports.fields_api import check_definition_access

        env = MagicMock()

        def check_access(model, perm):
            raise PermissionError(model)

        env.check_access = check_access
        env.registry = {"res.partner": MagicMock(_name="res.partner")}
        with self.assertRaises(PermissionError):
            check_definition_access(env, {
                "root": "res.partner",
                "columns": [{"expr": "name"}],
            })

    def test_list_exportable_unknown_model(self):
        from pyvelm.reports.fields_api import list_exportable_fields

        env = MagicMock(registry={})
        with self.assertRaises(ValueError):
            list_exportable_fields(env, "nope.model")


if __name__ == "__main__":
    unittest.main()
