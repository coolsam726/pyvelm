"""Targeted coverage for modules still below ~95%."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Date, Float, Integer, Many2many, Many2one, Monetary, One2many, Registry, Text, depends
from pyvelm.reports.fields_api import (
    _resolve_drill_context,
    check_definition_access,
    list_active_currencies,
    list_exportable_fields,
    list_fields_level,
    list_readable_models,
    models_in_definition,
    monetary_currency_path,
)
from pyvelm.reports.schema import ReportDefinitionError, validate_definition
from pyvelm.session_auth import resolve_session_uid, revoke_session, uses_stateless_sessions
from pyvelm.workflow.schema import WorkflowDefinitionError, validate_definition as wf_validate

_WF_SAMPLE = {
    "version": 1,
    "model": "wf.target",
    "states": [
        {"key": "draft", "label": "Draft", "initial": True},
        {"key": "done", "label": "Done"},
    ],
    "transitions": [
        {
            "key": "finish",
            "label": "Finish",
            "from": ["draft"],
            "to": "done",
            "kind": "user",
        },
    ],
}


def _wf_registry():
    reg = Registry()
    with reg.activate():

        class Target(BaseModel):
            _name = "wf.target"
            name = Char()
            owner_id = Many2one("res.users")

        reg.register(Target)
    return reg


def _partner_registry():
    reg = Registry()
    with reg.activate():

        class Country(BaseModel):
            _name = "res.country"
            _table = "res_country"
            name = Char()
            _secret = Char()

            @depends("name")
            def _compute_code_label(self):
                pass

            code_label = Char(compute="_compute_code_label", store=False)

        class Partner(BaseModel):
            _name = "res.partner"
            _table = "res_partner"
            name = Char()
            email = Char()
            amount = Float()
            amount_m = Monetary(currency_field="currency_id")
            create_date = Date()
            country_id = Many2one("res.country")
            currency_id = Many2one("res.currency")
            parent_id = Many2one("res.partner")
            child_ids = One2many("res.partner", inverse_name="parent_id")
            tag_ids = Many2many("res.tag")
            _secret = Char()

            @depends("name")
            def _compute_label(self):
                pass

            label = Char(compute="_compute_label", store=False)

        class Tag(BaseModel):
            _name = "res.tag"
            _table = "res_tag"
            name = Char()
            partner_ids = Many2many("res.partner")

        class Currency(BaseModel):
            _name = "res.currency"
            _table = "res_currency"
            code = Char()
            name = Char()
            symbol = Char()
            active = Char(default="True")

        Partner._fields["_secret"].private = True
        Country._fields["_secret"].private = True

    return reg


class WorkflowSchemaGapTests(unittest.TestCase):
    def setUp(self):
        self.reg = _wf_registry()

    def _defn(self, **extra):
        d = json.loads(json.dumps(_WF_SAMPLE))
        d.update(extra)
        return d

    def test_unknown_model_and_bad_states(self):
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(model="nope.model"), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(states=[]), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(states="bad"), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(states=[1]), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(states=[{"key": "", "label": "X", "initial": True}]),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    states=[
                        {"key": "draft", "label": "Draft", "initial": True},
                        {"key": "draft", "label": "Dup"},
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(states=[{"key": "draft", "label": "", "initial": True}]),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    states=[
                        {"key": "draft", "label": "Draft", "initial": True},
                        {"key": "done", "label": "Done", "initial": True},
                    ]
                ),
                self.reg,
            )

    def test_transition_shape_errors(self):
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(transitions="x"), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(self._defn(transitions=[1]), self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {"key": "", "label": "L", "from": ["draft"], "to": "done"}
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {"key": "a", "label": "A", "from": ["draft"], "to": "done"},
                        {"key": "a", "label": "B", "from": ["draft"], "to": "done"},
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {"key": "a", "label": "", "from": ["draft"], "to": "done"}
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": [],
                            "to": "done",
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": ["missing"],
                            "to": "done",
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": ["draft"],
                            "to": "done",
                            "reject_to": "nope",
                        }
                    ]
                ),
                self.reg,
            )

    def test_approval_and_form_validation(self):
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": ["draft"],
                            "to": "done",
                            "kind": "approval",
                            "approval": "bad",
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": ["draft"],
                            "to": "done",
                            "kind": "approval",
                            "approval": {
                                "strategy": "weird",
                                "assignee_type": "group",
                            },
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "a",
                            "label": "A",
                            "from": ["draft"],
                            "to": "done",
                            "kind": "approval",
                            "approval": {
                                "strategy": "any",
                                "assignee_type": "bogus",
                            },
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": "bad",
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {"fields": "bad"},
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {"fields": [1]},
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {
                                "fields": [
                                    {"name": "", "source": "stage", "type": "char"},
                                ],
                            },
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {
                                "fields": [
                                    {
                                        "name": "note",
                                        "source": "bogus",
                                        "type": "char",
                                    },
                                ],
                            },
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {
                                "fields": [
                                    {
                                        "name": "note",
                                        "source": "stage",
                                        "type": "bogus",
                                    },
                                ],
                            },
                        }
                    ]
                ),
                self.reg,
            )
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(
                self._defn(
                    transitions=[
                        {
                            "key": "submit",
                            "label": "Submit",
                            "from": ["draft"],
                            "to": "done",
                            "form": {
                                "fields": [
                                    {
                                        "name": "missing_on_model",
                                        "source": "record",
                                    },
                                ],
                            },
                        }
                    ]
                ),
                self.reg,
            )


class ReportSchemaGapTests(unittest.TestCase):
    def setUp(self):
        self.reg = _partner_registry()

    def _base(self, **extra):
        d = {
            "version": 1,
            "root": "res.partner",
            "columns": [{"expr": "name", "label": "Name"}],
        }
        d.update(extra)
        return d

    def test_root_and_column_errors(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(root=""), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(root="nope.model"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(columns=[]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(measures=[1]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(columns=[1]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "name", "label": ""}]),
                self.reg,
            )

    def test_aggregate_and_format_errors(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "amount",
                        "label": "A",
                        "aggregate": "bogus",
                    }],
                    groupby=["country_id"],
                    measures=["__count"],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "child_ids.name",
                        "label": "Kids",
                        "subaggregate": "bogus",
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "amount",
                        "label": "A",
                        "aggregate": "sum",
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "name",
                        "label": "N",
                        "format": "bad",
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "name",
                        "label": "N",
                        "format": {"type": "bogus"},
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "name",
                        "label": "N",
                        "format": {"align": "justify"},
                    }],
                ),
                self.reg,
            )

    def test_measures_and_parameters_list_types(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(measures="bad"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(groupby="bad"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(parameter_filters="bad"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(filters=[1]), self.reg)

    def test_field_path_and_order_errors(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(columns=[{"expr": "_secret", "label": "S"}]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(columns=[{"expr": "label", "label": "L"}]), self.reg)
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
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["country_id"],
                    "measures": ["label"],
                },
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(order=[1]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["country_id"],
                    "measures": ["__count"],
                    "order": ["bogus asc"],
                },
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(filters=[("bad_field", "=", "x")]),
                self.reg,
            )

    def test_aggregate_columns_type_and_entry_shapes(self):
        agg = {
            "version": 1,
            "root": "res.partner",
            "columns": "bad",
            "groupby": ["country_id"],
            "measures": ["__count"],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(agg, self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {**agg, "columns": [], "groupby": [1], "measures": ["__count"]},
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {**agg, "columns": [], "groupby": ["country_id"], "measures": [1]},
                self.reg,
            )

    def test_list_type_and_parameter_shape_errors(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(filters="bad"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(parameters="bad"), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(parameters=[1]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(parameters=[{"name": "", "type": "string"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    parameters=[
                        {"name": "q", "type": "string"},
                        {"name": "q", "type": "string"},
                    ],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(order="bad"), self.reg)

    def test_order_and_path_validation_success_and_failure(self):
        validate_definition(
            self._base(
                columns=[{"expr": "country_id.name", "label": "Country"}],
                order=["id asc", "country_id.name asc"],
            ),
            self.reg,
        )
        validate_definition(self._base(columns=[{"expr": "id", "label": "ID"}]), self.reg)
        validate_definition(
            self._base(
                columns=[{"expr": "child_ids.name", "label": "Kids"}],
                filters=[("id", "=", 1), ("country_id.name", "=", "x")],
                parameter_filters=[["name", "=", {"param": "q"}]],
                parameters=[{"name": "q", "type": "string"}],
            ),
            self.reg,
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(order=["nope asc"]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "missing_field", "label": "X"}]),
                self.reg,
            )

    def test_m2o_o2m_leaf_and_format_errors(self):
        with self.assertRaises(ValueError):
            validate_definition(
                self._base(columns=[{"expr": "country_id.nope", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ValueError):
            validate_definition(
                self._base(columns=[{"expr": "child_ids.nope", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "country_id._secret", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "country_id.code_label", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "child_ids._secret", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "child_ids.label", "label": "X"}]),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "name",
                        "label": "N",
                        "format": {"symbol": 1},
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "amount_m",
                        "label": "A",
                        "format": {
                            "type": "currency",
                            "currency_source": "bogus",
                        },
                    }],
                ),
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{
                        "expr": "amount_m",
                        "label": "A",
                        "format": {
                            "type": "currency",
                            "currency_source": "fixed",
                            "currency_id": "nope",
                        },
                    }],
                ),
                self.reg,
            )

    def test_groupby_without_measures_with_columns(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(
                    columns=[{"expr": "name", "label": "Name"}],
                    groupby=["country_id"],
                    measures=[],
                ),
                self.reg,
            )

    def test_groupby_measure_and_domain_leaf_errors(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["nope"],
                    "measures": ["__count"],
                },
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                {
                    "version": 1,
                    "root": "res.partner",
                    "columns": [],
                    "groupby": ["country_id"],
                    "measures": ["nope"],
                },
                self.reg,
            )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(filters=[("=", "x")]), self.reg)
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(filters=[(1, "=", "x")]), self.reg)

    @patch("pyvelm.reports.schema.parse_path")
    def test_m2o_unknown_leaf_field(self, parse_path_mock):
        from pyvelm.paths import M2oHop, Path
        from unittest.mock import MagicMock

        field_mock = MagicMock()
        parse_path_mock.return_value = Path(
            source_model="res.partner",
            hops=[M2oHop("res.partner", "country_id", field_mock, "res.country")],
            leaf_model="res.country",
            leaf_attr="nope",
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "country_id.nope", "label": "X"}]),
                self.reg,
            )

    @patch("pyvelm.reports.schema.parse_path")
    def test_o2m_unknown_leaf_attr(self, parse_path_mock):
        from pyvelm.paths import O2mHop, Path
        from unittest.mock import MagicMock

        field_mock = MagicMock()
        parse_path_mock.return_value = Path(
            source_model="res.partner",
            hops=[O2mHop("res.partner", "child_ids", field_mock, "res.partner", "parent_id")],
            leaf_model="res.partner",
            leaf_attr="nope",
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "child_ids.nope", "label": "X"}]),
                self.reg,
            )

    @patch("pyvelm.reports.schema.parse_path")
    def test_o2m_unknown_comodel(self, parse_path_mock):
        from pyvelm.paths import O2mHop, Path
        from unittest.mock import MagicMock

        field_mock = MagicMock()
        parse_path_mock.return_value = Path(
            source_model="res.partner",
            hops=[O2mHop("res.partner", "child_ids", field_mock, "res.missing", "parent_id")],
            leaf_model="res.missing",
            leaf_attr="name",
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(
                self._base(columns=[{"expr": "tag_ids.name", "label": "Tags"}]),
                self.reg,
            )


class FieldsApiGapTests(unittest.TestCase):
    def setUp(self):
        self.reg = _partner_registry()

    def _env(self, *, deny: set[str] | None = None):
        deny = deny or set()

        class Env:
            registry = self.reg

            def check_access(self, model, op):
                if model in deny:
                    raise PermissionError(model)
                return None

            def __getitem__(self, name):
                return self.registry[name]

        return Env()

    def test_monetary_currency_path(self):
        self.assertEqual(monetary_currency_path("amount", "currency_id"), "currency_id")
        self.assertEqual(
            monetary_currency_path("company_id.amount", "currency_id"),
            "company_id.currency_id",
        )

    def test_list_active_currencies_permission_and_sort(self):
        env = self._env(deny={"res.currency"})
        self.assertEqual(list_active_currencies(env), [])

        class Env2:
            registry = self.reg

            def check_access(self, model, op):
                return None

            def __getitem__(self, name):
                cur = MagicMock()
                cur.search.return_value = [
                    MagicMock(id=2, code="USD", name="Dollar", symbol="$"),
                    MagicMock(id=1, code="EUR", name="Euro", symbol="€"),
                ]
                return cur

        rows = list_active_currencies(Env2())
        self.assertEqual(rows[0]["code"], "EUR")

    def test_list_readable_models_skips_denied(self):
        env = self._env(deny={"res.tag"})
        models = list_readable_models(env)
        names = {m["value"] for m in models}
        self.assertIn("res.partner", names)
        self.assertNotIn("res.tag", names)

    def test_list_exportable_skips_denied_relations(self):
        env = self._env(deny={"res.country"})
        data = list_exportable_fields(env, "res.partner")
        exprs = {p["expr"] for p in data["paths"]}
        self.assertNotIn("country_id", exprs)

    def test_drill_context_and_level_errors(self):
        env = self._env()
        with self.assertRaises(ValueError):
            _resolve_drill_context("res.partner", "nope", self.reg)
        with self.assertRaises(ValueError):
            list_fields_level(env, "nope.model")
        with self.assertRaises(ValueError):
            list_fields_level(env, "res.partner", prefix="name")

    def test_models_in_definition_and_access(self):
        defn = {
            "root": "res.partner",
            "columns": [{"expr": "country_id.name"}],
            "filters": [["name", "=", "x"]],
            "parameter_filters": [["bad", "=", {"param": "q"}]],
        }
        models = models_in_definition(defn, self.reg)
        self.assertIn("res.country", models)
        check_definition_access(self._env(), {
            "root": "res.partner",
            "columns": [{"expr": "name"}],
        })

    def test_list_exportable_collection_paths_and_depth(self):
        self.reg["res.partner"]._fields["child_ids"].is_stored = True
        self.reg["res.partner"]._fields["tag_ids"].is_stored = True
        env = self._env()
        data = list_exportable_fields(env, "res.partner", max_depth=0)
        data = list_exportable_fields(env, "res.partner")
        kinds = {p["kind"] for p in data["paths"]}
        self.assertIn("collection", kinds)
        self.assertIn("m2o", kinds)
        shallow = list_exportable_fields(env, "res.partner", max_depth=1)
        deep_exprs = {f["expr"] for f in data["fields"]}
        shallow_exprs = {f["expr"] for f in shallow["fields"]}
        self.assertTrue(len(deep_exprs) >= len(shallow_exprs))

    def test_list_fields_level_skips_denied_comodels(self):
        self.reg["res.partner"]._fields["child_ids"].is_stored = True
        self.reg["res.partner"]._fields["tag_ids"].is_stored = True
        env = self._env(deny={"res.tag", "res.country"})
        items = list_fields_level(env, "res.partner")["items"]
        names = {i["name"] for i in items}
        self.assertNotIn("tag_ids", names)
        self.assertNotIn("country_id", names)

    def test_list_fields_level_drill_and_monetary(self):
        self.reg["res.partner"]._fields["child_ids"].is_stored = True
        self.reg["res.partner"]._fields["tag_ids"].is_stored = True
        env = self._env()
        root = list_fields_level(env, "res.partner")
        self.assertEqual(root["prefix"], "")
        tag = next(i for i in root["items"] if i["name"] == "tag_ids")
        self.assertEqual(tag["kind"], "collection")
        self.assertIn("subaggregates", tag)
        monetary = next(i for i in root["items"] if i["name"] == "amount_m")
        self.assertEqual(monetary["currency_field"], "currency_id")

        child_level = list_fields_level(env, "res.partner", prefix="child_ids")
        self.assertEqual(child_level["model"], "res.partner")
        child_id = next(i for i in child_level["items"] if i["name"] == "id")
        self.assertEqual(child_id["expr"], "child_ids.id")

        current, crumbs = _resolve_drill_context("res.partner", "country_id", self.reg)
        self.assertEqual(current._name, "res.country")
        self.assertEqual(len(crumbs), 2)

    def test_list_readable_skips_internal_models(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "res.partner"
                name = Char()

            class Internal(BaseModel):
                _name = "_internal.model"
                note = Char()

        reg._models["no.fields"] = object()
        env = type("Env", (), {"registry": reg, "check_access": lambda _s, _m, _o: None})()
        names = {m["value"] for m in list_readable_models(env)}
        self.assertIn("res.partner", names)
        self.assertNotIn("_internal.model", names)

    def test_models_in_definition_groupby_and_domain_paths(self):
        defn = {
            "root": "res.partner",
            "columns": [],
            "groupby": ["country_id"],
            "measures": ["__count"],
            "filters": [["country_id.name", "=", "x"]],
            "parameter_filters": [["country_id.name", "=", {"param": "q"}]],
        }
        models = models_in_definition(defn, self.reg)
        self.assertIn("res.country", models)

        bad_leaf = {
            "root": "res.partner",
            "columns": [],
            "filters": [("bad", "=", "x")],
        }
        models_bad = models_in_definition(bad_leaf, self.reg)
        self.assertIn("res.partner", models_bad)

    @patch("pyvelm.domain.iter_domain_leaves", side_effect=ValueError("bad"))
    def test_models_in_definition_skips_bad_domain(self, _iter_mock):
        defn = {"root": "res.partner", "columns": [], "parameter_filters": [["x", "=", 1]]}
        models = models_in_definition(defn, self.reg)
        self.assertEqual(models, {"res.partner"})

    @patch("pyvelm.domain.iter_domain_leaves")
    def test_models_in_definition_skips_short_leaves(self, iter_mock):
        iter_mock.return_value = iter([
            ("country_id.name", "=", "x"),
            ("bad",),
        ])
        defn = {
            "root": "res.partner",
            "columns": [],
            "filters": [["country_id.name", "=", "x"]],
        }
        models = models_in_definition(defn, self.reg)
        self.assertIn("res.country", models)


class SessionAuthGapTests(unittest.TestCase):
    def setUp(self):
        uses_stateless_sessions.cache_clear()

    def tearDown(self):
        uses_stateless_sessions.cache_clear()

    def test_stateless_inactive_user_returns_none(self):
        from pyvelm import Environment
        from pyvelm.session_auth import mint_session_cookie

        reg = Registry()
        with reg.activate():

            class Users(BaseModel):
                _name = "res.users"

        env = Environment(mock.Mock(), reg, uid=None)
        rs = mock.Mock()
        rs.__bool__ = mock.Mock(return_value=False)
        model = mock.Mock()
        model.search = mock.Mock(return_value=rs)
        sudo_env = mock.Mock()
        sudo_env.__getitem__ = mock.Mock(return_value=model)
        env.sudo = mock.Mock(return_value=sudo_env)

        with mock.patch.dict(os.environ, {"VERCEL": "1", "PYVELM_SECRET_KEY": "k"}, clear=False):
            token = mint_session_cookie(9)
            self.assertIsNone(resolve_session_uid(env, token))

    def test_db_mode_no_match_and_no_users_model(self):
        from pyvelm import Environment

        clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("PYVELM_DSN", "PYVELM_STATELESS_SESSIONS", "VERCEL")
        }
        with mock.patch.dict(os.environ, clean, clear=True):
            uses_stateless_sessions.cache_clear()
            reg = Registry()
            env = Environment(mock.Mock(), reg, uid=None)
            self.assertIsNone(resolve_session_uid(env, "missing-token"))

            with reg.activate():

                class Users(BaseModel):
                    _name = "res.users"

            rs = mock.Mock()
            rs.__bool__ = mock.Mock(return_value=False)
            model = mock.Mock()
            model.search = mock.Mock(return_value=rs)
            sudo_env = mock.Mock()
            sudo_env.__getitem__ = mock.Mock(return_value=model)
            env.sudo = mock.Mock(return_value=sudo_env)
            self.assertIsNone(resolve_session_uid(env, "orphan-token"))

    def test_revoke_without_users_model(self):
        from pyvelm import Environment

        reg = Registry()
        env = Environment(mock.Mock(), reg, uid=None)
        with mock.patch.dict(os.environ, {}, clear=True):
            uses_stateless_sessions.cache_clear()
            revoke_session(env, "tok")


if __name__ == "__main__":
    unittest.main()
