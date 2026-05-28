"""Tests for workflow definition schema and engine."""
from __future__ import annotations

import json

import pytest

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Char, Environment, Registry, loader
from pyvelm.workflow.engine import WorkflowEngine
from pyvelm.workflow.schema import WorkflowDefinitionError, validate_definition


_SAMPLE_DEF = {
    "version": 1,
    "model": "workflow.sample",
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


def _sample_registry():
    reg = Registry()
    with reg.activate():

        class _Sample(BaseModel):
            _name = "workflow.sample"

            name = Char()

    return reg


def test_validate_definition_ok():
    validate_definition(_SAMPLE_DEF, _sample_registry())


def test_validate_definition_auto_start_boolean():
    reg = _sample_registry()
    defn = {**_SAMPLE_DEF, "auto_start": True}
    validate_definition(defn, reg)
    with pytest.raises(WorkflowDefinitionError):
        validate_definition({**_SAMPLE_DEF, "auto_start": "yes"}, reg)


def test_validate_definition_rejects_duplicate_state():
    reg = _sample_registry()
    bad = {
        **_SAMPLE_DEF,
        "states": [
            {"key": "draft", "label": "Draft", "initial": True},
            {"key": "draft", "label": "Other", "initial": False},
        ],
    }
    with pytest.raises(WorkflowDefinitionError):
        validate_definition(bad, reg)


@pytest.fixture
def workflow_env():
    import psycopg
    from pathlib import Path

    dsn = __import__("os").environ.get("PYVELM_DSN")
    if not dsn:
        pytest.skip("PYVELM_DSN not set")
    examples = Path(__file__).resolve().parents[2] / "examples" / "modules"
    reg = Registry()
    with psycopg.connect(dsn, autocommit=True) as conn:
        env = Environment(conn, registry=reg, uid=1)
        env._acl_bypass = True
        loader.load_and_install(list(BUILTIN_MODULE_ROOTS) + [examples], env)
        yield env


def test_workflow_start_and_transition(workflow_env):
    if "workflow.definition" not in workflow_env.registry:
        pytest.skip("workflow module not installed")
    if "res.partner" not in workflow_env.registry:
        pytest.skip("res.partner not installed (need examples/modules)")
    env = workflow_env
    Definition = env["workflow.definition"]
    Partner = env["res.partner"]
    rec = Partner.create({"name": "Workflow test partner", "code": "WF01"})
    inst = WorkflowEngine.start(env, rec)
    assert inst.state == "draft"
    WorkflowEngine.apply_transition(
        env, inst, "submit",
        {"submission_note": "Looks good"},
    )
    assert inst.pending_transition == "submit"
    Approval = env["workflow.approval"]
    pending = Approval.search([("instance_id", "=", inst.id), ("status", "=", "pending")])
    assert pending
    WorkflowEngine.approve(env, next(iter(pending)), approved=True)
    assert inst.state == "approved"
