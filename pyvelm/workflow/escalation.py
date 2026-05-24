"""Overdue approval escalation (cron-driven)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .engine import parse_definition, _transition_by_key


def process_overdue_approvals(env) -> int:
    """Escalate or notify on pending approvals past ``deadline_at``.

    Returns the number of approvals processed.
    """
    if "workflow.approval" not in env.registry:
        return 0
    Approval = env["workflow.approval"]
    now = datetime.utcnow()
    pending = Approval.search([("status", "=", "pending")])
    count = 0
    for appr in pending:
        if not appr.deadline_at:
            continue
        deadline = appr.deadline_at
        if hasattr(deadline, "replace"):
            pass
        if deadline > now:
            continue
        if _escalate_one(env, appr):
            count += 1
    return count


def _escalate_one(env, approval) -> bool:
    instance = approval.instance_id
    if not instance:
        return False
    defn = parse_definition(instance.definition_id.definition)
    tr = _transition_by_key(defn, approval.transition_key)
    cfg = tr.get("approval") or {}
    escalate_gid = cfg.get("escalate_to_group_id")
    if not escalate_gid:
        _notify_overdue(env, approval, instance)
        return False

    approval.write({"status": "cancelled"})
    Approval = env["workflow.approval"]
    Approval.create({
        "instance_id": instance.id,
        "transition_key": approval.transition_key,
        "status": "pending",
        "requester_id": approval.requester_id.id if approval.requester_id else False,
        "assignee_group_id": int(escalate_gid),
        "sequence": (approval.sequence or 0) + 100,
        "form_data": approval.form_data or "{}",
        "deadline_at": datetime.utcnow() + timedelta(
            hours=int(cfg.get("deadline_hours") or 24)
        ),
    })
    record = env[instance.res_model].browse(instance.res_id)
    if hasattr(record, "message_post"):
        try:
            record.message_post(
                f"Approval escalated to group {escalate_gid} (was overdue).",
                subtype="workflow",
            )
        except Exception:  # noqa: BLE001
            pass
    return True


def _notify_overdue(env, approval, instance) -> None:
    record = env[instance.res_model].browse(instance.res_id)
    if hasattr(record, "message_post"):
        try:
            record.message_post(
                "Approval request is overdue.",
                subtype="workflow",
            )
        except Exception:  # noqa: BLE001
            pass
