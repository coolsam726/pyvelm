"""Targeted coverage for modules still below ~95%."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Float, Integer, Many2many, Many2one, One2many, Registry, Text, depends
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

        class Partner(BaseModel):
            _name = "res.partner"
            _table = "res_partner"
            name = Char()
            email = Char()
            amount = Float()
            country_id = Many2one("res.country")
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
