"""High-level workflow helpers for UI and APIs."""
from __future__ import annotations

import json
from typing import Any

from .engine import WorkflowEngine, parse_definition
from .schema import validate_definition


def definition_dict(record) -> dict:
    return parse_definition(record.definition)


def save_definition(env, record, meta: dict, defn: dict) -> None:
    validate_definition(defn, env.registry)
    model = meta.get("model") or defn.get("model")
    active = bool(meta.get("active", record.active))
    if active and "workflow.definition" in env.registry:
        Definition = env["workflow.definition"]
        for other in Definition.search([("model", "=", model), ("active", "=", True)]):
            if other.id != record.id:
                other.write({"active": False})
    record.write({
        "name": meta.get("name", record.name),
        "description": meta.get("description", record.description),
        "model": model,
        "definition": json.dumps(defn, indent=2),
        "active": active,
    })


def form_context(env, res_model: str, res_id: int) -> dict[str, Any] | None:
    """Workflow bar context for a record form, or None."""
    if "workflow.instance" not in env.registry:
        return None
    readonly = False
    try:
        env.check_access("workflow.instance", "read")
    except PermissionError:
        # Read-only workflow bar: don't require broad workflow grants just to
        # *see* status/history for a record the user is already allowed to view.
        # Any action endpoints still enforce their own checks.
        readonly = True
        env = env.sudo()

    inst = WorkflowEngine.instance_for_record(env, res_model, res_id)
    if inst is None:
        defn_rec = WorkflowEngine.active_definition(env, res_model)
        if defn_rec is None:
            return None
        defn = parse_definition(defn_rec.definition)
        if defn.get("auto_start"):
            from .runtime import maybe_auto_start_workflow

            record = env[res_model].browse(res_id)
            if record:
                if not readonly:
                    maybe_auto_start_workflow(env, record)
                    inst = WorkflowEngine.instance_for_record(env, res_model, res_id)

    if inst is None:
        defn_rec = WorkflowEngine.active_definition(env, res_model)
        if defn_rec is None:
            return None
        defn = parse_definition(defn_rec.definition)
        return {
            "has_workflow": True,
            "started": False,
            "definition_name": defn_rec.name,
            "can_start": False if readonly else True,
            "auto_start": bool(defn.get("auto_start")),
            "statusbar": _statusbar_from_defn(defn, current_key=None),
            "timeline": [],
            "readonly": readonly,
        }

    defn = parse_definition(inst.definition_id.definition)
    state_label = inst.state
    for st in defn.get("states") or []:
        if st.get("key") == inst.state:
            state_label = st.get("label", inst.state)
            break

    pending_approvals = []
    if "workflow.approval" in env.registry and env.uid:
        Approval = env["workflow.approval"]
        for appr in Approval.search([
            ("instance_id", "=", inst.id),
            ("status", "=", "pending"),
        ]):
            if env.uid == 1:
                pending_approvals.append(_approval_ui(appr, defn))
                continue
            try:
                from .engine import _user_may_act_on_approval
                if _user_may_act_on_approval(env, appr, env.uid):
                    pending_approvals.append(_approval_ui(appr, defn))
            except (PermissionError, ValueError, TypeError):
                pass

    statusbar = _statusbar_from_defn(defn, current_key=inst.state)

    from .history import record_timeline

    timeline = record_timeline(
        env,
        res_model,
        res_id,
        instance_id=inst.id,
        definition_json=inst.definition_id.definition,
    )

    transitions = []
    if not readonly:
        transitions = WorkflowEngine.available_transitions(env, inst)

    return {
        "has_workflow": True,
        "started": True,
        "instance_id": inst.id,
        "state": inst.state,
        "state_label": state_label,
        "pending_transition": inst.pending_transition or "",
        "transitions": transitions,
        "pending_approvals": pending_approvals,
        "can_start": False,
        "auto_start": bool(defn.get("auto_start")),
        "statusbar": statusbar,
        "timeline": timeline,
        "readonly": readonly,
    }


def _statusbar_from_defn(defn: dict, *, current_key: str | None) -> list[dict]:
    states_list = defn.get("states") or []
    current_idx = next(
        (i for i, st in enumerate(states_list) if st.get("key") == current_key),
        -1,
    )
    out: list[dict] = []
    for i, st in enumerate(states_list):
        key = st.get("key", "")
        current = key == current_key
        out.append({
            "key": key,
            "label": st.get("label", key),
            "current": current,
            "done": current_idx >= 0 and i < current_idx,
            "final": bool(st.get("final")),
            "cancelled": bool(st.get("cancelled")),
        })
    return out


def backfill_auto_start(env, model_name: str) -> int:
    """Start workflows on existing rows that missed ``auto_start`` (e.g. after Sync)."""
    if "workflow.definition" not in env.registry:
        return 0
    defn_rec = WorkflowEngine.active_definition(env, model_name)
    if defn_rec is None:
        return 0
    defn = parse_definition(defn_rec.definition)
    if not defn.get("auto_start"):
        return 0
    from .runtime import maybe_auto_start_workflow

    Model = env[model_name]
    count = 0
    for rec in Model.search([]):
        if WorkflowEngine.instance_for_record(env, model_name, rec.id):
            continue
        maybe_auto_start_workflow(env, rec)
        if WorkflowEngine.instance_for_record(env, model_name, rec.id):
            count += 1
    return count


def _approval_ui(appr, defn: dict) -> dict:
    tr_label = appr.transition_key or ""
    for tr in defn.get("transitions") or []:
        if tr.get("key") == appr.transition_key:
            tr_label = tr.get("label", appr.transition_key)
            break
    return {
        "id": appr.id,
        "transition_key": appr.transition_key,
        "transition_label": tr_label,
        "requester": appr.requester_id.name if appr.requester_id else "",
    }


def list_groups(env) -> list[dict]:
    if "res.groups" not in env.registry:
        return []
    try:
        env.check_access("res.groups", "read")
    except PermissionError:
        return []
    Group = env["res.groups"]
    return [
        {"id": g.id, "name": g.name or f"Group {g.id}"}
        for g in sorted(Group.search([]), key=lambda r: (r.name or "", r.id))
    ]


def list_users(env) -> list[dict]:
    if "res.users" not in env.registry:
        return []
    try:
        env.check_access("res.users", "read")
    except PermissionError:
        return []
    User = env["res.users"]
    return [
        {"id": u.id, "name": u.name or u.login or f"User {u.id}", "login": u.login or ""}
        for u in sorted(User.search([]), key=lambda r: (r.name or "", r.id))
    ]


def list_model_fields(env, model_name: str) -> list[dict]:
    """Writable fields on *model_name* for the workflow form designer."""
    if model_name not in env.registry:
        return []
    try:
        env.check_access(model_name, "read")
        env.check_access(model_name, "write")
    except PermissionError:
        return []

    cls = env.registry[model_name]
    out: list[dict] = []
    for fname, field in sorted(getattr(cls, "_fields", {}).items()):
        if fname in ("id", "create_uid", "write_uid"):
            continue
        if getattr(field, "readonly", False):
            continue
        ftype = field.__class__.__name__.replace("Field", "").lower()
        if ftype.endswith("field"):
            ftype = ftype[:-5]
        comodel = getattr(field, "comodel_name", None)
        out.append({
            "name": fname,
            "label": getattr(field, "string", None) or fname.replace("_", " ").title(),
            "type": ftype,
            "source": "record",
            "comodel": comodel,
        })
    return out
