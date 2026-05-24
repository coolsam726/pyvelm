"""Runtime workflow engine — instances, transitions, approvals."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from .schema import WorkflowDefinitionError, validate_definition


def _first(records):
    """First record from a search recordset (recordsets are not subscriptable)."""
    if not records:
        return None
    return next(iter(records))


def parse_definition(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        defn = raw
    else:
        defn = json.loads(raw or "{}")
    return defn


class WorkflowEngine:
    """Stateless workflow operations backed by ``workflow.*`` models."""

    @staticmethod
    def active_definition(env, model_name: str):
        if "workflow.definition" not in env.registry:
            return None
        Definition = env["workflow.definition"]
        recs = Definition.search([
            ("model", "=", model_name),
            ("active", "=", True),
        ], order="id desc", limit=1)
        return _first(recs)

    @staticmethod
    def instance_for_record(env, res_model: str, res_id: int):
        if "workflow.instance" not in env.registry:
            return None
        Instance = env["workflow.instance"]
        recs = Instance.search([
            ("res_model", "=", res_model),
            ("res_id", "=", res_id),
            ("active", "=", True),
        ], limit=1)
        return _first(recs)

    @staticmethod
    def start(env, record, definition=None):
        """Attach a workflow instance to *record* (returns instance)."""
        model_name = record._name
        if definition is None:
            definition = WorkflowEngine.active_definition(env, model_name)
        if definition is None:
            raise WorkflowDefinitionError(f"No active workflow for {model_name!r}")
        definition.ensure_one()
        defn = parse_definition(definition.definition)
        validate_definition(defn, env.registry)
        if defn["model"] != model_name:
            raise WorkflowDefinitionError("Workflow model mismatch")

        existing = WorkflowEngine.instance_for_record(env, model_name, record.id)
        if existing:
            return existing

        initial = _initial_state(defn)
        Instance = env["workflow.instance"]
        inst = Instance.create({
            "definition_id": definition.id,
            "res_model": model_name,
            "res_id": record.id,
            "state": initial,
            "stage_data": "{}",
            "started_by": env.uid,
            "active": True,
        })
        _post_chatter(env, record, f"Workflow started — state «{initial}»")
        return inst

    @staticmethod
    def available_transitions(env, instance, *, user_id: int | None = None) -> list[dict]:
        """Transitions the current user may trigger from *instance*'s state."""
        instance.ensure_one()
        defn = parse_definition(instance.definition_id.definition)
        uid = user_id if user_id is not None else env.uid
        if instance.pending_transition:
            return []
        out: list[dict] = []
        for tr in defn.get("transitions") or []:
            if instance.state not in (tr.get("from") or []):
                continue
            if not _user_may_trigger(env, instance, tr, uid):
                continue
            out.append(_transition_ui(tr))
        return out

    @staticmethod
    def apply_transition(
        env,
        instance,
        transition_key: str,
        form_values: dict[str, Any] | None = None,
        *,
        user_id: int | None = None,
    ):
        """Run *transition_key*; returns updated instance."""
        instance.ensure_one()
        if instance.pending_transition:
            raise WorkflowDefinitionError("A transition is already awaiting approval")
        defn = parse_definition(instance.definition_id.definition)
        tr = _transition_by_key(defn, transition_key)
        if instance.state not in (tr.get("from") or []):
            raise WorkflowDefinitionError(
                f"Transition {transition_key!r} not allowed from state {instance.state!r}"
            )
        uid = user_id if user_id is not None else env.uid
        if not _user_may_trigger(env, instance, tr, uid):
            raise PermissionError("You cannot run this transition")

        form_values = form_values or {}
        _validate_form(tr, form_values)
        stage_patch, record_patch = _split_form_values(tr, form_values)
        stage_data = _load_json(instance.stage_data)
        stage_data.update(stage_patch)

        record = env[instance.res_model].browse(instance.res_id)
        if record_patch:
            record.write(record_patch)

        kind = tr.get("kind", "user")
        if kind == "approval":
            WorkflowEngine._start_approval(env, instance, tr, stage_data, uid)
            instance.write({
                "stage_data": json.dumps(stage_data),
                "pending_transition": transition_key,
            })
            _post_chatter(
                env, record,
                f"Submitted for approval — «{tr.get('label', transition_key)}»",
            )
            return instance

        instance.write({
            "state": tr["to"],
            "stage_data": json.dumps(stage_data),
            "pending_transition": False,
            "state_updated_at": datetime.utcnow(),
        })
        _post_chatter(
            env, record,
            f"Moved to «{tr['to']}» via «{tr.get('label', transition_key)}»",
        )
        return instance

    @staticmethod
    def approve(
        env,
        approval,
        *,
        approved: bool = True,
        comment: str = "",
        user_id: int | None = None,
    ):
        """Approve or reject a pending approval request."""
        approval.ensure_one()
        if approval.status != "pending":
            raise WorkflowDefinitionError("Approval is not pending")
        uid = user_id if user_id is not None else env.uid
        if not _user_may_act_on_approval(env, approval, uid):
            raise PermissionError("You cannot act on this approval")

        instance = approval.instance_id
        instance.ensure_one()
        defn = parse_definition(instance.definition_id.definition)
        tr = _transition_by_key(defn, approval.transition_key)

        approval.write({
            "status": "approved" if approved else "rejected",
            "acted_by": uid,
            "acted_at": datetime.utcnow(),
            "comment": comment or False,
        })
        if "workflow.task" in env.registry and uid:
            Task = env["workflow.task"]
            for task in Task.search([
                ("instance_id", "=", instance.id),
                ("user_id", "=", uid),
                ("state", "=", "open"),
            ]):
                task.write({"state": "done" if approved else "cancelled"})

        record = env[instance.res_model].browse(instance.res_id)
        if not approved:
            reject_to = tr.get("reject_to") or (tr.get("from") or ["draft"])[0]
            instance.write({
                "state": reject_to,
                "pending_transition": False,
                "state_updated_at": datetime.utcnow(),
            })
            _post_chatter(env, record, f"Approval rejected — returned to «{reject_to}»")
            return instance

        if not _approvals_complete(env, instance, tr):
            _maybe_advance_sequential(env, instance, tr)
            return instance

        instance.write({
            "state": tr["to"],
            "pending_transition": False,
            "state_updated_at": datetime.utcnow(),
        })
        _post_chatter(
            env, record,
            f"Approved — moved to «{tr['to']}»",
        )
        return instance

    @staticmethod
    def _start_approval(env, instance, tr: dict, stage_data: dict, requester_id: int) -> None:
        Approval = env["workflow.approval"]
        approval_cfg = tr.get("approval") or {}
        strategy = approval_cfg.get("strategy", "any")
        assignees = _resolve_assignees(env, instance, tr, requester_id)
        if not assignees:
            raise WorkflowDefinitionError("No approvers resolved for this transition")

        deadline = _approval_deadline(approval_cfg)
        stage_data = dict(stage_data)

        if strategy == "sequential":
            stage_data["_wf_queue"] = assignees[1:]
            _create_approval(env, instance, tr, assignees[0], requester_id, stage_data, 1, deadline)
            instance.write({"stage_data": json.dumps(stage_data)})
            return

        for i, spec in enumerate(assignees, start=1):
            _create_approval(env, instance, tr, spec, requester_id, stage_data, i, deadline)


def _initial_state(defn: dict) -> str:
    for st in defn.get("states") or []:
        if st.get("initial"):
            return st["key"]
    raise WorkflowDefinitionError("No initial state")


def _transition_by_key(defn: dict, key: str) -> dict:
    for tr in defn.get("transitions") or []:
        if tr.get("key") == key:
            return tr
    raise WorkflowDefinitionError(f"Unknown transition {key!r}")


def _transition_ui(tr: dict) -> dict:
    form = tr.get("form") or {}
    return {
        "key": tr["key"],
        "label": tr.get("label", tr["key"]),
        "kind": tr.get("kind", "user"),
        "form_title": form.get("title") or tr.get("label", tr["key"]),
        "form_fields": form.get("fields") or [],
    }


def _user_may_trigger(env, instance, tr: dict, uid: int | None) -> bool:
    if uid == 1:
        return True
    kind = tr.get("kind", "user")
    if kind == "automatic":
        return False
    return True


def _user_may_act_on_approval(env, approval, uid: int | None) -> bool:
    if uid == 1:
        return True
    if approval.assignee_user_id:
        auid = (
            approval.assignee_user_id.id
            if hasattr(approval.assignee_user_id, "id")
            else int(approval.assignee_user_id)
        )
        if auid == uid:
            return True
    if approval.assignee_group_id:
        gid = (
            approval.assignee_group_id.id
            if hasattr(approval.assignee_group_id, "id")
            else int(approval.assignee_group_id)
        )
        User = env["res.users"]
        users = User.search([("group_ids", "in", gid)])
        return any(u.id == uid for u in users)
    return False


def _resolve_assignees(env, instance, tr: dict, requester_id: int) -> list[dict]:
    approval = tr.get("approval") or {}
    assignee_type = approval.get("assignee_type", "group")
    strategy = approval.get("strategy", "any")
    if assignee_type == "user":
        user_id = approval.get("user_id")
        if not user_id:
            raise WorkflowDefinitionError("approval.user_id required")
        return [{"user_id": int(user_id)}]
    if assignee_type == "field":
        record = env[instance.res_model].browse(instance.res_id)
        field = approval.get("user_field")
        val = getattr(record, field, None)
        if not val:
            return []
        uid = val.id if hasattr(val, "id") else int(val)
        return [{"user_id": uid}]
    group_id = approval.get("group_id")
    if not group_id:
        Group = env["res.groups"]
        admins = Group.search([("name", "=", "Admin")], limit=1)
        group_id = admins.id if admins else None
    if not group_id:
        return []
    if strategy in ("all", "sequential"):
        User = env["res.users"]
        users = User.search([("group_ids", "in", int(group_id))])
        if users:
            return [{"user_id": u.id} for u in users]
    return [{"group_id": int(group_id)}]


def _create_approval(
    env,
    instance,
    tr: dict,
    spec: dict,
    requester_id: int,
    stage_data: dict,
    sequence: int,
    deadline,
) -> None:
    Approval = env["workflow.approval"]
    vals: dict[str, Any] = {
        "instance_id": instance.id,
        "transition_key": tr["key"],
        "status": "pending",
        "requester_id": requester_id,
        "sequence": sequence,
        "form_data": json.dumps({k: v for k, v in stage_data.items() if not k.startswith("_wf")}),
    }
    if deadline:
        vals["deadline_at"] = deadline
    if spec.get("user_id"):
        vals["assignee_user_id"] = spec["user_id"]
    if spec.get("group_id"):
        vals["assignee_group_id"] = spec["group_id"]
    Approval.create(vals)
    _maybe_create_approval_task(env, instance, tr, spec)


def _maybe_create_approval_task(env, instance, tr: dict, spec: dict) -> None:
    if "workflow.task" not in env.registry:
        return
    uid = spec.get("user_id")
    if not uid:
        return
    Task = env["workflow.task"]
    Task.create({
        "name": f"Approve: {tr.get('label', tr.get('key', 'request'))}",
        "description": f"Workflow approval on {instance.res_model} #{instance.res_id}",
        "user_id": int(uid),
        "state": "open",
        "priority": "high",
        "res_model": instance.res_model,
        "res_id": instance.res_id,
        "instance_id": instance.id,
    })


def _approval_deadline(approval_cfg: dict):
    hours = approval_cfg.get("deadline_hours")
    if not hours:
        return None
    try:
        return datetime.utcnow() + timedelta(hours=int(hours))
    except (TypeError, ValueError):
        return None


def _maybe_advance_sequential(env, instance, tr: dict) -> None:
    approval_cfg = tr.get("approval") or {}
    if approval_cfg.get("strategy") != "sequential":
        return
    stage_data = _load_json(instance.stage_data)
    queue = stage_data.get("_wf_queue") or []
    if not queue:
        return
    next_spec = queue.pop(0)
    stage_data["_wf_queue"] = queue
    instance.write({"stage_data": json.dumps(stage_data)})
    deadline = _approval_deadline(approval_cfg)
    pending_count = len(
        env["workflow.approval"].search([
            ("instance_id", "=", instance.id),
            ("transition_key", "=", tr["key"]),
        ])
    )
    _create_approval(
        env, instance, tr, next_spec,
        env.uid or 1,
        stage_data,
        pending_count + 1,
        deadline,
    )


def _approvals_complete(env, instance, tr: dict) -> bool:
    Approval = env["workflow.approval"]
    pending = Approval.search([
        ("instance_id", "=", instance.id),
        ("transition_key", "=", tr["key"]),
        ("status", "=", "pending"),
    ])
    if pending:
        return False
    stage_data = _load_json(instance.stage_data)
    if stage_data.get("_wf_queue"):
        return False
    strategy = (tr.get("approval") or {}).get("strategy", "any")
    approvals = Approval.search([
        ("instance_id", "=", instance.id),
        ("transition_key", "=", tr["key"]),
        ("status", "in", ["approved", "rejected", "cancelled"]),
    ])
    approved = [a for a in approvals if a.status == "approved"]
    rejected = [a for a in approvals if a.status == "rejected"]
    if rejected:
        return False
    if strategy == "all":
        return len(approved) == len(approvals) and len(approved) > 0
    return len(approved) >= 1


def _validate_form(tr: dict, form_values: dict) -> None:
    for ff in (tr.get("form") or {}).get("fields") or []:
        if not ff.get("required"):
            continue
        name = ff["name"]
        val = form_values.get(name)
        if val is None or val == "" or val is False:
            label = ff.get("label") or name
            raise WorkflowDefinitionError(f"{label} is required")


def _split_form_values(tr: dict, form_values: dict) -> tuple[dict, dict]:
    stage: dict = {}
    record: dict = {}
    field_map = {ff["name"]: ff for ff in (tr.get("form") or {}).get("fields") or []}
    for key, val in form_values.items():
        spec = field_map.get(key)
        if not spec:
            continue
        if spec.get("source", "stage") == "record":
            record[key] = val
        else:
            stage[key] = val
    return stage, record


def _load_json(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    return json.loads(raw)


def _post_chatter(env, record, body: str) -> None:
    if hasattr(record, "message_post"):
        try:
            record.message_post(body, subtype="workflow")
        except Exception:  # noqa: BLE001
            pass
