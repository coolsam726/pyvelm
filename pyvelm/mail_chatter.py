"""General mail chatter context for record forms (Odoo-style)."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .workflow.history import _author_name, _format_time, classify_workflow_body

CHATTER_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All"),
    ("notes", "Notes"),
    ("emails", "Emails"),
    ("tracking", "Changes"),
)

_VALID_FILTERS = {k for k, _ in CHATTER_FILTERS}


def _normalize_filter(value: str | None) -> str:
    key = (value or "all").strip().lower()
    return key if key in _VALID_FILTERS else "all"


def _subtype_label(subtype: str, *, message_type: str = "", has_email: bool = False) -> str:
    if subtype == "mail_tracking":
        return "Field change"
    if has_email or message_type == "email":
        return "Email"
    if subtype == "note":
        return "Note"
    if message_type == "notification":
        return "System"
    return "Log"


def _author_initials(author_name: str) -> str:
    name = (author_name or "").strip()
    if not name:
        return "?"
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _email_state_label(state: str | None) -> str:
    s = (state or "").strip().lower()
    if s == "sent":
        return "Sent"
    if s == "failed":
        return "Failed"
    if s == "outgoing":
        return "Queued"
    return ""


def _attachments_for_messages(env, message_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not message_ids or "ir.attachment" not in env.registry:
        return {}
    try:
        env.check_access("ir.attachment", "read")
    except PermissionError:
        return {}
    Att = env["ir.attachment"]
    rows = Att.search([
        ("res_model", "=", "mail.message"),
        ("res_id", "in", message_ids),
    ])
    out: dict[int, list[dict[str, Any]]] = {}
    for att in rows:
        rid = att.res_id
        if rid is None:
            continue
        out.setdefault(int(rid), []).append({
            "id": att.id,
            "name": att.name or att.datas_fname or f"file-{att.id}",
            "mimetype": att.mimetype or "",
            "size": att.file_size or 0,
            "download_url": f"/api/attachment/{att.id}/download",
        })
    for lst in out.values():
        lst.sort(key=lambda a: a["id"])
    return out


def _message_event(msg, env, *, att_map: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    body = (msg.body or "").strip()
    subtype = getattr(msg, "subtype", None) or ""
    message_type = getattr(msg, "message_type", None) or ""
    recipient = (getattr(msg, "recipient_email", None) or "").strip()
    has_email = bool(recipient)
    kind, variant = classify_workflow_body(body, subtype=subtype)
    author = _author_name(env, msg.author_id)
    return {
        "id": msg.id,
        "kind": kind,
        "variant": variant,
        "subtype": subtype,
        "message_type": message_type,
        "subtype_label": _subtype_label(
            subtype, message_type=message_type, has_email=has_email
        ),
        "body": body,
        "author": author,
        "author_initials": _author_initials(author),
        "at": msg.date.isoformat() if hasattr(msg.date, "isoformat") and msg.date else None,
        "at_display": _format_time(msg.date, env),
        "recipient_email": recipient,
        "email_state": _email_state_label(getattr(msg, "state", None)) if has_email else "",
        "email_subject": (getattr(msg, "subject", None) or "").strip(),
        "attachments": att_map.get(msg.id, []),
    }


def _matches_filter(event: dict[str, Any], filter_key: str) -> bool:
    if filter_key == "all":
        return True
    subtype = event.get("subtype") or ""
    if filter_key == "tracking":
        return subtype == "mail_tracking"
    if filter_key == "emails":
        return bool(event.get("recipient_email")) or event.get("message_type") == "email"
    if filter_key == "notes":
        return (
            subtype != "mail_tracking"
            and not event.get("recipient_email")
            and event.get("message_type") != "email"
        )
    return True


def record_chatter_messages(
    env,
    res_model: str,
    res_id: int,
    *,
    filter_key: str = "all",
) -> list[dict[str, Any]]:
    """Non-workflow messages for the record, newest first."""
    filter_key = _normalize_filter(filter_key)
    if "mail.message" not in env.registry:
        return []
    try:
        env.check_access("mail.message", "read")
    except PermissionError:
        return []
    Message = env["mail.message"]
    msgs = Message.search([
        ("model", "=", res_model),
        ("res_id", "=", res_id),
    ])
    msg_list = [m for m in msgs if (getattr(m, "subtype", None) or "") != "workflow"]
    att_map = _attachments_for_messages(env, [m.id for m in msg_list])
    events = [_message_event(m, env, att_map=att_map) for m in msg_list]
    events = [e for e in events if _matches_filter(e, filter_key)]
    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    return events


def form_chatter_context(
    env,
    res_model: str,
    res_id: int,
    *,
    enabled: bool,
    filter_key: str = "all",
    composer_mode: str = "note",
) -> dict[str, Any] | None:
    """Template context for ``_chatter_panel.html``, or ``None`` when disabled."""
    if not enabled or not res_id:
        return None
    if res_model not in env.registry:
        return None
    filter_key = _normalize_filter(filter_key)
    composer_mode = "email" if (composer_mode or "").strip().lower() == "email" else "note"
    can_post = False
    try:
        env.check_access(res_model, "write")
        can_post = True
    except PermissionError:
        pass
    panel_base = (
        f"/web/chatter/panel?model={quote(res_model, safe='')}"
        f"&res_id={res_id}&mode={composer_mode}"
    )
    return {
        "enabled": True,
        "model": res_model,
        "res_id": res_id,
        "filter": filter_key,
        "filters": [
            {
                "key": k,
                "label": lbl,
                "href": f"{panel_base}&filter={k}",
            }
            for k, lbl in CHATTER_FILTERS
        ],
        "composer_mode": composer_mode,
        "messages": record_chatter_messages(env, res_model, res_id, filter_key=filter_key),
        "can_post": can_post,
        "attachments_enabled": "ir.attachment" in env.registry,
        "post_url": "/web/chatter/post",
        "panel_url": "/web/chatter/panel",
        # Surface the rich composer entry point only when mail_compose
        # is installed and the user can compose. URL builds a fresh
        # draft pre-bound to this record (to/cc/bcc/template are filled
        # in by the composer launch endpoint).
        "compose_url": (
            f"/web/mail/compose/launch?model={quote(res_model, safe='')}&res_id={res_id}"
            if can_post and "mail.compose.message" in env.registry
            else ""
        ),
        "error": None,
    }


def _parse_attachment_ids(raw_values: list[str]) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        if not raw:
            continue
        for part in str(raw).replace(" ", "").split(","):
            if part.isdigit():
                n = int(part)
                if n not in seen:
                    seen.add(n)
                    ids.append(n)
    return ids


def post_chatter_message(
    env,
    res_model: str,
    res_id: int,
    body: str,
    *,
    action: str = "note",
    recipient_email: str = "",
    subject: str = "",
    attachment_ids: list[int] | None = None,
) -> None:
    """Log a note or queue an email on a MailThread record."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Message body is required.")
    if res_model not in env.registry:
        raise ValueError(f"Unknown model {res_model!r}")
    env.check_access(res_model, "write")
    model_cls = env.registry[res_model]
    from .mail import MailThread

    if not issubclass(model_cls, MailThread):
        raise ValueError(f"{res_model} does not support chatter")
    rec = env[res_model].browse(res_id)
    if not rec:
        raise ValueError("Record not found")
    rec.ensure_one()
    att_ids = attachment_ids or []
    if action == "email":
        email = (recipient_email or "").strip()
        if not email:
            raise ValueError("Recipient email is required to send a message.")
        subj = (subject or "").strip() or (body[:80] if body else "")
        rec.notify(
            body,
            recipient_email=email,
            subject=subj,
            subtype="email",
            attachment_ids=att_ids or None,
        )
    else:
        rec.message_post(
            body,
            subtype="note",
            message_type="comment",
            attachment_ids=att_ids or None,
        )


def post_chatter_note(env, res_model: str, res_id: int, body: str) -> None:
    """Backward-compatible alias for internal notes."""
    post_chatter_message(env, res_model, res_id, body, action="note")
