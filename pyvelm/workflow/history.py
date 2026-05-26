"""Workflow history timeline for a record form."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import parse_definition


def classify_workflow_body(body: str, *, subtype: str = "") -> tuple[str, str]:
    """Return ``(kind, variant)`` for a workflow chatter line."""
    if subtype == "mail_tracking":
        return "tracking", "muted"
    text = (body or "").strip()
    lower = text.lower()
    if lower.startswith("workflow started"):
        return "started", "brand"
    if "submitted for approval" in lower:
        return "submitted", "warning"
    if lower.startswith("approval rejected"):
        return "rejected", "danger"
    if " approved — now at " in lower:
        return "signoff", "success"
    if lower.startswith("approved"):
        return "approved", "success"
    if lower.startswith("moved to"):
        return "transition", "success"
    return "note", "muted"


def _format_time(value, env) -> str:
    if value is None:
        return ""
    if not hasattr(value, "strftime"):
        return str(value)
    try:
        from pyvelm.render import _utc_to_local

        local = _utc_to_local(value, env) or value
    except (ImportError, ValueError, TypeError):
        local = value
    return local.strftime("%Y-%m-%d %H:%M")


def _author_name(env, user_id) -> str:
    if not user_id or "res.users" not in env.registry:
        return ""
    try:
        env.check_access("res.users", "read")
    except PermissionError:
        return ""
    user = env["res.users"].browse(user_id.id if hasattr(user_id, "id") else user_id)
    if not user:
        return ""
    user.ensure_one()
    return user.name or user.login or ""


def _transition_label(defn: dict, key: str) -> str:
    for tr in defn.get("transitions") or []:
        if tr.get("key") == key:
            return tr.get("label", key)
    return key


def _message_event(msg, env) -> dict[str, Any]:
    body = msg.body or ""
    kind, variant = classify_workflow_body(
        body, subtype=getattr(msg, "subtype", None) or ""
    )
    return {
        "id": f"msg-{msg.id}",
        "kind": kind,
        "variant": variant,
        "title": body,
        "body": "",
        "author": _author_name(env, msg.author_id),
        "at": msg.date.isoformat() if hasattr(msg.date, "isoformat") and msg.date else None,
        "at_display": _format_time(msg.date, env),
        "pending": False,
    }


def _approval_event(appr, env, defn: dict) -> dict[str, Any]:
    tr_label = _transition_label(defn, appr.transition_key or "")
    assignee = ""
    if appr.assignee_user_id:
        assignee = _author_name(env, appr.assignee_user_id)
    elif appr.assignee_group_id and "res.groups" in env.registry:
        try:
            g = appr.assignee_group_id
            g.ensure_one()
            assignee = g.name or ""
        except (PermissionError, ValueError, TypeError):
            pass

    if appr.status == "pending":
        return {
            "id": f"appr-pending-{appr.id}",
            "kind": "pending",
            "variant": "warning",
            "title": f"Awaiting approval — {tr_label}",
            "body": f"Assigned to {assignee}" if assignee else "",
            "author": _author_name(env, appr.requester_id),
            "at": None,
            "at_display": "Pending",
            "pending": True,
        }

    acted = appr.status in ("approved", "rejected")
    if not acted:
        return {
            "id": f"appr-{appr.id}",
            "kind": "note",
            "variant": "muted",
            "title": f"{tr_label} ({appr.status})",
            "body": appr.comment or "",
            "author": _author_name(env, appr.acted_by or appr.requester_id),
            "at": None,
            "at_display": "",
            "pending": False,
        }

    kind = "approved" if appr.status == "approved" else "rejected"
    variant = "success" if appr.status == "approved" else "danger"
    title = f"{'Approved' if appr.status == 'approved' else 'Rejected'} — {tr_label}"
    body = (appr.comment or "").strip()
    return {
        "id": f"appr-{appr.id}",
        "kind": kind,
        "variant": variant,
        "title": title,
        "body": body,
        "author": _author_name(env, appr.acted_by),
        "at": appr.acted_at.isoformat() if hasattr(appr.acted_at, "isoformat") and appr.acted_at else None,
        "at_display": _format_time(appr.acted_at, env),
        "pending": False,
    }


def record_timeline(
    env,
    res_model: str,
    res_id: int,
    *,
    instance_id: int | None = None,
    definition_json: str | None = None,
) -> list[dict[str, Any]]:
    """Ordered workflow events for the record form timeline."""
    events: list[dict[str, Any]] = []
    defn: dict = {}
    if definition_json:
        defn = parse_definition(definition_json)

    if "mail.message" in env.registry:
        domain = [
            ("model", "=", res_model),
            ("res_id", "=", res_id),
            ("subtype", "=", "workflow"),
        ]
        try:
            env.check_access("mail.message", "read")
            Message = env["mail.message"]
            msgs = Message.search(domain)
        except PermissionError:
            # Workflow history is part of the record UX; it should not require
            # granting broad read access to *all* mail.message rows.
            # Narrow sudo fallback: only fetch workflow-subtype messages for
            # the specific record we're rendering.
            Message = env.sudo()["mail.message"]
            msgs = Message.search(domain)

        for msg in sorted(msgs, key=lambda m: m.date or datetime.min):
            events.append(_message_event(msg, env))

    pending_events: list[dict[str, Any]] = []
    approval_history: list[dict[str, Any]] = []
    if instance_id and "workflow.approval" in env.registry:
        try:
            env.check_access("workflow.approval", "read")
            Approval = env["workflow.approval"]
            for appr in Approval.search([("instance_id", "=", instance_id)]):
                if appr.status == "pending":
                    pending_events.append(_approval_event(appr, env, defn))
                elif appr.acted_at:
                    approval_history.append(_approval_event(appr, env, defn))
        except PermissionError:
            pass

    if not events and approval_history:
        approval_history.sort(key=lambda e: e.get("at") or "")
        events = approval_history

    events.extend(pending_events)
    return events
