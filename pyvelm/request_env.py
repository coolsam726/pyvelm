"""Bind HTTP request cookies to an :class:`~pyvelm.env.Environment`.

Module routes that define their own ``get_env`` must call
:func:`apply_request_scope` the same way ``pyvelm.web.create_app`` does,
or company theme, sidebar accent, and record rules will not match the
UI company switcher.
"""
from __future__ import annotations

from typing import Callable

from pyvelm.env import Environment

SESSION_COOKIE = "pyvelm_session"
COMPANY_COOKIE = "pyvelm_company"
# Default session max-age mirrors ``session_cookie`` in ``pyvelm.web`` (30 days).
_DEFAULT_SESSION_LIFETIME_MIN = 30 * 24 * 60


def audit_context_from_request(request) -> dict[str, str | int]:
    """Metadata stored on ``env.context`` for the system_audit module."""
    client = getattr(request, "client", None)
    headers = getattr(request, "headers", None) or {}
    cookies = getattr(request, "cookies", None) or {}
    get_header = headers.get if hasattr(headers, "get") else lambda _k, _d="": ""
    get_cookie = cookies.get if hasattr(cookies, "get") else lambda _k, _d="": ""
    return {
        "audit_ip": getattr(client, "host", "") if client else "",
        "audit_user_agent": (get_header("user-agent") or "")[:500],
        "audit_session_id": get_cookie(SESSION_COOKIE) or "",
        "audit_session_lifetime_minutes": _DEFAULT_SESSION_LIFETIME_MIN,
    }


def apply_request_scope(
    env: Environment,
    request,
    *,
    resolve_session: Callable[[Environment, str | None], int | None],
    resolve_basic: Callable[[Environment, str | None], int | None],
) -> Environment:
    """Apply session uid and active company from request cookies/headers."""
    uid = resolve_session(env, request.cookies.get(SESSION_COOKIE))
    if uid is None:
        uid = resolve_basic(env, request.headers.get("authorization"))
    if uid is not None:
        env.uid = uid
        env._user_groups_cache = None  # type: ignore[attr-defined]
        env._access_cache.clear()
        env.prime_current_user_cache()

    raw_company = request.cookies.get(COMPANY_COOKIE)
    if raw_company:
        try:
            env = env.with_company(int(raw_company))
        except (ValueError, TypeError):
            pass
    return env.with_context(**audit_context_from_request(request))
