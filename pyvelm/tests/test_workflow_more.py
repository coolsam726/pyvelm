"""Additional unit tests for ``pyvelm.workflow`` (schema + engine + runtime)."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Char, Registry
from pyvelm.workflow import runtime as workflow_runtime
from pyvelm.workflow.engine import (
    WorkflowEngine,
    _approval_complete_message,
    _approval_deadline,
    _approvals_complete,
    _first,
    _initial_state,
    _load_json,
    _post_chatter,
    _resolve_assignees,
    _split_form_values,
    _transition_by_key,
    _transition_ui,
    _user_may_act_on_approval,
    _user_may_trigger,
    _validate_form,
    parse_definition,
)
from pyvelm.workflow.schema import WorkflowDefinitionError, validate_definition

_SAMPLE = {
    "version": 1,
    "model": "wf.target",
    "states": [
        {"key": "draft", "label": "Draft", "initial": True},
        {"key": "done", "label": "Done", "final": True},
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


def _registry():
    reg = Registry()
    with reg.activate():

        class Target(BaseModel):
            _name = "wf.target"
            _table = "wf_target"
            name = Char()
            owner_id = Char()

        reg.register(Target)
    return reg


def _recordset(*rows):
    rs = MagicMock()
    rs.__iter__ = lambda self: iter(rows)
    rs.__bool__ = lambda self: bool(rows)
    if rows:
        rs.__len__ = lambda self: len(rows)
    return rs


def _row(**kwargs):
    rec = MagicMock()
    for k, v in kwargs.items():
        setattr(rec, k, v)
    rec.ensure_one = MagicMock()
    rec.write = MagicMock()
    rec.message_post = MagicMock()
    return rec


class ParseDefinitionTests(unittest.TestCase):
    def test_parse_json_string(self):
        self.assertEqual(parse_definition('{"version": 1}')["version"], 1)

    def test_first_helper(self):
        self.assertIsNone(_first(_recordset()))
        self.assertEqual(_first(_recordset(_row(id=1))).id, 1)


class SchemaValidationTests(unittest.TestCase):
    def setUp(self):
        self.reg = _registry()

    def test_rejects_non_object(self):
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition([], self.reg)

    def test_rejects_bad_version_and_model(self):
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition({"version": 2, "model": "wf.target", "states": _SAMPLE["states"]}, self.reg)
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition({"version": 1, "states": _SAMPLE["states"]}, self.reg)

    def test_rejects_state_and_transition_shape_errors(self):
        bad_states = {
            **_SAMPLE,
            "states": [{"key": "draft", "label": "Draft"}],
        }
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(bad_states, self.reg)

        bad_trans = {
            **_SAMPLE,
            "transitions": [{"key": "x", "label": "X", "from": ["draft"], "to": "missing"}],
        }
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(bad_trans, self.reg)

    def test_rejects_invalid_transition_kind_and_approval(self):
        defn = {
            **_SAMPLE,
            "transitions": [
                {
                    "key": "bad",
                    "label": "Bad",
                    "from": ["draft"],
                    "to": "done",
                    "kind": "magic",
                }
            ],
        }
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(defn, self.reg)

    def test_approval_transition_requires_valid_assignee_field(self):
        defn = {
            **_SAMPLE,
            "transitions": [
                {
                    "key": "appr",
                    "label": "Approve",
                    "from": ["draft"],
                    "to": "done",
                    "kind": "approval",
                    "approval": {
                        "strategy": "all",
                        "assignee_type": "field",
                        "user_field": "missing_field",
                    },
                }
            ],
        }
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(defn, self.reg)

    def test_form_field_validation(self):
        defn = {
            **_SAMPLE,
            "transitions": [
                {
                    "key": "submit",
                    "label": "Submit",
                    "from": ["draft"],
                    "to": "done",
                    "form": {
                        "fields": [
                            {"name": "note", "label": "Note", "source": "stage", "type": "text"},
                            {"name": "name", "label": "Name", "source": "record"},
                            {"name": "note", "label": "Dup", "source": "stage", "type": "char"},
                        ],
                    },
                }
            ],
        }
        with self.assertRaises(WorkflowDefinitionError):
            validate_definition(defn, self.reg)


class EngineHelperTests(unittest.TestCase):
    def test_initial_state_and_transition_lookup(self):
        self.assertEqual(_initial_state(_SAMPLE), "draft")
        tr = _transition_by_key(_SAMPLE, "finish")
        self.assertEqual(tr["to"], "done")
        with self.assertRaises(WorkflowDefinitionError):
            _transition_by_key(_SAMPLE, "nope")

    def test_transition_ui_and_messages(self):
        tr = _SAMPLE["transitions"][0]
        ui = _transition_ui(tr)
        self.assertEqual(ui["key"], "finish")
        msg = _approval_complete_message(_SAMPLE, tr)
        self.assertIn("Done", msg)

    def test_load_json_variants(self):
        self.assertEqual(_load_json(None), {})
        self.assertEqual(_load_json({"a": 1})["a"], 1)
        self.assertEqual(_load_json('{"b": 2}')["b"], 2)

    def test_validate_form_required(self):
        tr = {
            "form": {
                "fields": [
                    {"name": "note", "label": "Note", "required": True, "source": "stage"},
                ],
            },
        }
        with self.assertRaises(WorkflowDefinitionError):
            _validate_form(tr, {})
        _validate_form(tr, {"note": "ok"})

    def test_split_form_values(self):
        tr = {
            "form": {
                "fields": [
                    {"name": "note", "source": "stage"},
                    {"name": "name", "source": "record"},
                ],
            },
        }
        stage, record = _split_form_values(tr, {"note": "a", "name": "b", "extra": "x"})
        self.assertEqual(stage, {"note": "a"})
        self.assertEqual(record, {"name": "b"})

    def test_user_may_trigger_automatic(self):
        inst = _row(id=1)
        tr = {"kind": "automatic"}
        self.assertTrue(_user_may_trigger(MagicMock(), inst, tr, 1))
        self.assertFalse(_user_may_trigger(MagicMock(), inst, tr, 2))

    def test_user_may_act_on_approval_by_user_and_group(self):
        env = MagicMock()
        approval = _row(
            assignee_user_id=_row(id=5),
            assignee_group_id=None,
        )
        self.assertTrue(_user_may_act_on_approval(env, approval, 5))
        self.assertFalse(_user_may_act_on_approval(env, approval, 9))

        approval2 = _row(
            assignee_user_id=None,
            assignee_group_id=_row(id=3),
        )
        User = MagicMock()
        User.search.return_value = _recordset(_row(id=7))
        env.__getitem__ = lambda _s, k: User if k == "res.users" else MagicMock()
        self.assertTrue(_user_may_act_on_approval(env, approval2, 7))

    def test_post_chatter_swallows_errors(self):
        rec = MagicMock()
        rec.message_post.side_effect = RuntimeError("no mail")
        _post_chatter(MagicMock(), rec, "hello")

    def test_approval_deadline_hours(self):
        deadline = _approval_deadline({"deadline_hours": 24})
        self.assertIsNotNone(deadline)
        self.assertIsNone(_approval_deadline({}))
        self.assertIsNone(_approval_deadline({"deadline_hours": "bad"}))

    def test_resolve_assignees_user_and_field(self):
        env = MagicMock()
        tr_user = {"approval": {"assignee_type": "user", "user_id": 9}}
        self.assertEqual(_resolve_assignees(env, _row(), tr_user, 1), [{"user_id": 9}])

        record = _row(owner_id=_row(id=4))
        Target = MagicMock()
        Target.browse.return_value = record
        env.__getitem__ = lambda _e, n: Target
        tr_field = {"approval": {"assignee_type": "field", "user_field": "owner_id"}}
        self.assertEqual(
            _resolve_assignees(env, _row(res_model="wf.target", res_id=1), tr_field, 1),
            [{"user_id": 4}],
        )

    def test_approvals_complete_any_strategy(self):
        env = MagicMock()
        inst = _row(id=1, stage_data="{}")
        tr = {"key": "finish", "approval": {"strategy": "any"}}
        Approval = MagicMock()
        Approval.search.side_effect = [
            _recordset(),
            _recordset(_row(status="approved")),
        ]
        env.__getitem__ = lambda _e, n: Approval
        self.assertTrue(_approvals_complete(env, inst, tr))


class EngineMockedFlowTests(unittest.TestCase):
    def test_start_creates_instance(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 1

        definition = _row(
            id=10,
            definition=json.dumps(_SAMPLE),
        )
        definition.ensure_one = MagicMock()

        instance = _row(id=99, state="draft")
        Instance = MagicMock()
        Instance.search.return_value = _recordset()
        Instance.create.return_value = instance

        Definition = MagicMock()
        Definition.search.return_value = _recordset(definition)

        Target = MagicMock()
        target_row = _row(id=1, _name="wf.target")
        Target.browse.return_value = target_row

        def _getitem(_env, name):
            return {
                "workflow.definition": Definition,
                "workflow.instance": Instance,
                "wf.target": Target,
            }[name]

        env.__getitem__ = _getitem

        inst = WorkflowEngine.start(env, target_row, definition)
        self.assertEqual(inst.id, 99)
        Instance.create.assert_called_once()

    def test_apply_transition_user_kind(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 2

        definition = _row(id=1, definition=json.dumps(_SAMPLE))
        instance = _row(
            id=5,
            state="draft",
            pending_transition=False,
            stage_data="{}",
            res_model="wf.target",
            res_id=1,
            definition_id=definition,
        )

        Target = MagicMock()
        Target.browse.return_value = _row(id=1, message_post=MagicMock())
        env.__getitem__ = lambda _env, n: Target if n == "wf.target" else MagicMock()

        WorkflowEngine.apply_transition(env, instance, "finish", {})
        instance.write.assert_called()
        written = instance.write.call_args[0][0]
        self.assertEqual(written["state"], "done")

    def test_available_transitions_empty_when_pending(self):
        instance = _row(state="draft", pending_transition="finish")
        instance.definition_id = _row(definition=json.dumps(_SAMPLE))
        env = MagicMock()
        self.assertEqual(WorkflowEngine.available_transitions(env, instance), [])

    def test_start_returns_existing_instance(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 1
        definition = _row(id=1, definition=json.dumps(_SAMPLE))
        definition.ensure_one = MagicMock()
        existing = _row(id=50)
        record = _row(id=1, _name="wf.target")
        with patch.object(WorkflowEngine, "instance_for_record", return_value=existing):
            inst = WorkflowEngine.start(env, record, definition)
        self.assertIs(inst, existing)

    def test_approve_rejection_moves_to_reject_to(self):
        reg = _registry()
        defn = {
            **_SAMPLE,
            "transitions": [
                {
                    "key": "submit",
                    "label": "Submit",
                    "from": ["draft"],
                    "to": "done",
                    "kind": "approval",
                    "approval": {"strategy": "any", "assignee_type": "user", "user_id": 2},
                    "reject_to": "draft",
                }
            ],
        }
        env = MagicMock()
        env.registry = reg
        env.uid = 2
        definition = _row(definition=json.dumps(defn))
        instance = _row(
            id=1,
            state="draft",
            pending_transition="submit",
            stage_data="{}",
            res_model="wf.target",
            res_id=1,
            definition_id=definition,
        )
        approval = _row(
            status="pending",
            transition_key="submit",
            instance_id=instance,
            assignee_user_id=_row(id=2),
            assignee_group_id=None,
        )
        approval.ensure_one = MagicMock()
        Target = MagicMock()
        Target.browse.return_value = _row(message_post=MagicMock())
        env.__getitem__ = lambda _e, n: Target if n == "wf.target" else MagicMock()
        WorkflowEngine.approve(env, approval, approved=False, comment="no")
        instance.write.assert_called()
        self.assertEqual(instance.write.call_args[0][0]["state"], "draft")


class WorkflowRuntimeMoreTests(unittest.TestCase):
    def test_schema_ready_false_without_registry(self):
        env = MagicMock()
        env.registry = {}
        self.assertFalse(workflow_runtime._workflow_schema_ready(env))

    def test_schema_ready_checks_table(self):
        env = MagicMock()
        env.registry = {"workflow.definition": type("C", (), {"_table": "workflow_definition"})}
        env.conn.execute.return_value.fetchone.return_value = None
        self.assertFalse(workflow_runtime._workflow_schema_ready(env))
        env.conn.execute.return_value.fetchone.return_value = (1,)
        self.assertTrue(workflow_runtime._workflow_schema_ready(env))

    def test_maybe_auto_start_inner_starts_when_configured(self):
        reg = _registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 1
        env._acl_bypass = False
        env.transaction = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)))

        record = _row(id=3, _name="wf.target")
        definition = _row(id=1, definition=json.dumps({**_SAMPLE, "auto_start": True}))

        with patch.object(WorkflowEngine, "active_definition", return_value=definition), patch.object(
            WorkflowEngine, "instance_for_record", return_value=None
        ), patch.object(WorkflowEngine, "start") as start:
            workflow_runtime._maybe_auto_start_workflow_inner(env, record)
        start.assert_called_once()

    def test_maybe_auto_start_swallows_errors(self):
        env = MagicMock()
        env.registry = {"workflow.definition": type("C", (), {"_table": "workflow_definition"})}
        env._acl_bypass = False
        env.conn.execute.return_value.fetchone.return_value = ("workflow_definition",)
        env.transaction = MagicMock(side_effect=RuntimeError("boom"))
        workflow_runtime.maybe_auto_start_workflow(env, MagicMock(_name="wf.target"))


if __name__ == "__main__":
    unittest.main()
