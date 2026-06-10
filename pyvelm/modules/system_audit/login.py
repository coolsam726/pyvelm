"""Login / logout / failure events."""
from __future__ import annotations

from .context import request_context


def log_login_event(
    env,
    *,
    event: str,
    email: str | None = None,
    user_id: int | None = None,
) -> None:
    if "ir.login.log" not in env.registry:
        return
    ctx = request_context(env)
    env.sudo()["ir.login.log"].create(
        {
            "user_id": user_id,
            "email": email,
            "event": event,
            "ip_address": ctx["ip"] or None,
            "user_agent": ctx["user_agent"] or None,
            "session_id": ctx["session_id"] or None,
            "session_lifetime_minutes": ctx["session_lifetime_minutes"],
        }
    )
