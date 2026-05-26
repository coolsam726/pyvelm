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
    return env
