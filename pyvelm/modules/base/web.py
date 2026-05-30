"""Per-request company menu layout middleware for pyvelm ``base``.

Register via ``WEB_ROUTES = "base.web:register_routes"`` in base ``__pyvelm__``.
"""
from __future__ import annotations


def register_routes(app) -> None:
    registry = app.state.registry
    pool = app.state.pool

    if "res.company" not in registry or "res.users" not in registry:
        return

    from pyvelm import Environment
    from pyvelm.menu import reset_request_menu_layout, set_request_menu_layout
    from pyvelm.request_env import COMPANY_COOKIE, SESSION_COOKIE
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    def _resolve_company_layout(session_token: str, raw_company: str | None) -> str | None:
        from pyvelm.session_auth import resolve_session_uid

        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env._acl_bypass = True

            uid = resolve_session_uid(env, session_token)
            if uid is None:
                return None
            users = env["res.users"].browse(uid)

            cid: int | None = None
            if raw_company:
                try:
                    cid = int(raw_company)
                except (ValueError, TypeError):
                    cid = None
            if cid is None:
                try:
                    cid = users.company_id.id
                except Exception:
                    cid = None
            if not cid:
                return None

            co = env["res.company"].browse(cid)
            val = (getattr(co, "menu_layout", None) or "").strip()
            return val or None

    class MenuLayoutMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            import asyncio

            session_token = request.cookies.get(SESSION_COOKIE)
            if session_token:
                raw_company = request.cookies.get(COMPANY_COOKIE)
                loop = asyncio.get_event_loop()
                layout = await loop.run_in_executor(
                    None, _resolve_company_layout, session_token, raw_company
                )
                if layout:
                    ctx_token = set_request_menu_layout(layout)
                    try:
                        return await call_next(request)
                    finally:
                        reset_request_menu_layout(ctx_token)

            return await call_next(request)

    app.add_middleware(MenuLayoutMiddleware)
