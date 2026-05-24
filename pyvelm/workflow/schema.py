"""Workflow definition validation (schema v1)."""
from __future__ import annotations

from typing import Any

WORKFLOW_VERSION = 1

_VALID_TRANSITION_KINDS = frozenset({"user", "approval", "automatic"})
_VALID_APPROVAL_STRATEGIES = frozenset({"any", "all", "sequential"})
_VALID_ASSIGNEE_TYPES = frozenset({"user", "group", "field"})
_VALID_FIELD_SOURCES = frozenset({"record", "stage"})
_VALID_STAGE_FIELD_TYPES = frozenset({
    "char", "text", "integer", "float", "boolean", "date", "datetime", "selection",
})


class WorkflowDefinitionError(ValueError):
    """Raised when a workflow definition fails validation."""


def validate_definition(defn: dict[str, Any], registry) -> None:
    """Validate *defn* in place; raise ``WorkflowDefinitionError`` on failure."""
    if not isinstance(defn, dict):
        raise WorkflowDefinitionError("Definition must be a JSON object")
    version = defn.get("version", 1)
    if version != WORKFLOW_VERSION:
        raise WorkflowDefinitionError(
            f"Unsupported workflow version {version!r} (expected {WORKFLOW_VERSION})"
        )
    model = defn.get("model")
    if not model or not isinstance(model, str):
        raise WorkflowDefinitionError("'model' must be a model technical name")
    if model not in registry:
        raise WorkflowDefinitionError(f"Unknown model {model!r}")

    states = defn.get("states")
    if not states or not isinstance(states, list):
        raise WorkflowDefinitionError("'states' must be a non-empty list")

    state_keys: set[str] = set()
    initial_count = 0
    for i, st in enumerate(states):
        if not isinstance(st, dict):
            raise WorkflowDefinitionError(f"states[{i}] must be an object")
        key = st.get("key")
        if not key or not isinstance(key, str):
            raise WorkflowDefinitionError(f"states[{i}].key must be a string")
        if key in state_keys:
            raise WorkflowDefinitionError(f"Duplicate state key {key!r}")
        state_keys.add(key)
        label = st.get("label")
        if not label or not isinstance(label, str):
            raise WorkflowDefinitionError(f"states[{i}].label must be a string")
        if st.get("initial"):
            initial_count += 1

    if initial_count != 1:
        raise WorkflowDefinitionError("Exactly one state must have initial=true")

    if "auto_start" in defn and not isinstance(defn["auto_start"], bool):
        raise WorkflowDefinitionError("'auto_start' must be a boolean")

    transitions = defn.get("transitions") or []
    if not isinstance(transitions, list):
        raise WorkflowDefinitionError("'transitions' must be a list")

    trans_keys: set[str] = set()
    model_cls = registry[model]
    fields = getattr(model_cls, "_fields", {})

    for i, tr in enumerate(transitions):
        if not isinstance(tr, dict):
            raise WorkflowDefinitionError(f"transitions[{i}] must be an object")
        tkey = tr.get("key")
        if not tkey or not isinstance(tkey, str):
            raise WorkflowDefinitionError(f"transitions[{i}].key must be a string")
        if tkey in trans_keys:
            raise WorkflowDefinitionError(f"Duplicate transition key {tkey!r}")
        trans_keys.add(tkey)
        label = tr.get("label")
        if not label or not isinstance(label, str):
            raise WorkflowDefinitionError(f"transitions[{i}].label must be a string")
        to_state = tr.get("to")
        if not to_state or to_state not in state_keys:
            raise WorkflowDefinitionError(
                f"transitions[{i}].to must reference a defined state"
            )
        from_states = tr.get("from") or []
        if not isinstance(from_states, list) or not from_states:
            raise WorkflowDefinitionError(f"transitions[{i}].from must be a non-empty list")
        for fs in from_states:
            if fs not in state_keys:
                raise WorkflowDefinitionError(
                    f"transitions[{i}].from references unknown state {fs!r}"
                )
        kind = tr.get("kind", "user")
        if kind not in _VALID_TRANSITION_KINDS:
            raise WorkflowDefinitionError(f"transitions[{i}].kind {kind!r} invalid")
        reject_to = tr.get("reject_to")
        if reject_to is not None and reject_to not in state_keys:
            raise WorkflowDefinitionError(
                f"transitions[{i}].reject_to must reference a defined state"
            )
        if kind == "approval":
            approval = tr.get("approval") or {}
            if not isinstance(approval, dict):
                raise WorkflowDefinitionError(f"transitions[{i}].approval must be an object")
            strategy = approval.get("strategy", "any")
            if strategy not in _VALID_APPROVAL_STRATEGIES:
                raise WorkflowDefinitionError(
                    f"transitions[{i}].approval.strategy invalid"
                )
            assignee_type = approval.get("assignee_type", "group")
            if assignee_type not in _VALID_ASSIGNEE_TYPES:
                raise WorkflowDefinitionError(
                    f"transitions[{i}].approval.assignee_type invalid"
                )
            if assignee_type == "field":
                uf = approval.get("user_field")
                if not uf or uf not in fields:
                    raise WorkflowDefinitionError(
                        f"transitions[{i}].approval.user_field must be a model field"
                    )
        _validate_transition_form(tr, i, fields)


def _validate_transition_form(tr: dict, index: int, model_fields: dict) -> None:
    form = tr.get("form")
    if form is None:
        return
    if not isinstance(form, dict):
        raise WorkflowDefinitionError(f"transitions[{index}].form must be an object")
    form_fields = form.get("fields") or []
    if not isinstance(form_fields, list):
        raise WorkflowDefinitionError(f"transitions[{index}].form.fields must be a list")
    seen: set[str] = set()
    for j, ff in enumerate(form_fields):
        if not isinstance(ff, dict):
            raise WorkflowDefinitionError(
                f"transitions[{index}].form.fields[{j}] must be an object"
            )
        name = ff.get("name")
        if not name or not isinstance(name, str):
            raise WorkflowDefinitionError(
                f"transitions[{index}].form.fields[{j}].name required"
            )
        if name in seen:
            raise WorkflowDefinitionError(f"Duplicate form field {name!r}")
        seen.add(name)
        source = ff.get("source", "stage")
        if source not in _VALID_FIELD_SOURCES:
            raise WorkflowDefinitionError(
                f"transitions[{index}].form.fields[{j}].source invalid"
            )
        if source == "record":
            if name not in model_fields:
                raise WorkflowDefinitionError(
                    f"transitions[{index}].form.fields[{j}] unknown record field {name!r}"
                )
        else:
            ftype = ff.get("type", "char")
            if ftype not in _VALID_STAGE_FIELD_TYPES:
                raise WorkflowDefinitionError(
                    f"transitions[{index}].form.fields[{j}].type invalid"
                )
