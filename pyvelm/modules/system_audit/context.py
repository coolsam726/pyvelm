"""Request metadata captured from :class:`~pyvelm.env.Environment`.context."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyvelm.env import Environment

_DEFAULT_SESSION_LIFETIME_MIN = 120


def request_context(env: Environment) -> dict[str, str | int | None]:
    ctx = env.context or {}
    return {
        "ip": str(ctx.get("audit_ip") or ""),
        "user_agent": str(ctx.get("audit_user_agent") or "")[:500],
        "session_id": str(ctx.get("audit_session_id") or ""),
        "session_lifetime_minutes": int(
            ctx.get("audit_session_lifetime_minutes")
            or _DEFAULT_SESSION_LIFETIME_MIN
        ),
    }
