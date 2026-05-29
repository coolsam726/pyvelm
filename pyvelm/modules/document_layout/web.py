"""Print route — `GET /report/pdf/{key}/{record_id}` (0.24.0 WEB_ROUTES hook).

Renders a registered document to a branded PDF, enforcing login + read ACL
(documents carry real data, so this is NOT sudo).
"""
import base64
import binascii

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from pyvelm import Environment
from pyvelm.request_env import apply_request_scope

from . import layout as _layout

# NOTE: no `from __future__ import annotations` here — FastAPI resolves the
# `Request` / `Environment` type hints via module globals, so they must be
# real module-level imports (not function-local), and annotations must be live.


def register_routes(app) -> None:
    registry = app.state.registry
    pool = app.state.pool

    def _resolve_session(env, token):
        if not token or "res.users" not in env.registry:
            return None
        env._acl_bypass = True
        try:
            users = env["res.users"].search(
                [("session_token", "=", token), ("active", "=", True)], limit=1)
            return users.id if users else None
        finally:
            env._acl_bypass = False

    def _resolve_basic(env, header_value):
        if not header_value or not header_value.lower().startswith("basic "):
            return None
        try:
            raw = base64.b64decode(header_value.split(None, 1)[1])
            login, password = raw.decode("utf-8", "ignore").split(":", 1)
        except (binascii.Error, ValueError):
            return None
        if "res.users" not in env.registry:
            return None
        env._acl_bypass = True
        try:
            users = env["res.users"].search([("login", "=", login), ("active", "=", True)], limit=1)
            if users and users.check_password(password):
                return users.id
            return None
        finally:
            env._acl_bypass = False

    def get_env(request: Request):
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env = apply_request_scope(
                env, request,
                resolve_session=_resolve_session, resolve_basic=_resolve_basic,
            )
            yield env

    def _guard(env, key):
        """Auth + ACL + known-key checks shared by the print and preview routes."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        spec = _layout.document_spec(key)
        if not spec:
            raise HTTPException(status_code=404, detail=f"Unknown document {key!r}")
        try:
            env.check_access(spec["model"], "read")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return spec

    @app.get("/report/pdf/{key}/{record_id}")
    def print_document(key: str, record_id: int, env: Environment = Depends(get_env)):
        _guard(env, key)
        try:
            pdf_bytes, _ = _layout.render_pdf(env, key, record_id)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:  # wkhtmltopdf missing / failed
            raise HTTPException(status_code=503, detail=str(e)) from e
        return Response(
            content=pdf_bytes, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{key}-{record_id}.pdf"'},
        )

    @app.get("/report/html/{key}/{record_id}", response_class=HTMLResponse)
    def preview_document(key: str, record_id: int, env: Environment = Depends(get_env)):
        """Same rendered HTML the PDF is built from — view/refresh while editing
        templates or the document layout (no wkhtmltopdf round-trip)."""
        _guard(env, key)
        try:
            return HTMLResponse(_layout.render_html(env, key, record_id, preview=True))
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/report/layout/preview/{company_id}", response_class=HTMLResponse)
    def preview_layout(company_id: int, env: Environment = Depends(get_env)):
        """Preview a company's document layout with sample data (design-time)."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            env.check_access("res.company", "read")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        try:
            return HTMLResponse(_layout.render_layout_preview(env, company_id))
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    # ---- Layout designer (split editor + live preview) ------------------

    @app.get("/report/layout/designer", response_class=HTMLResponse)
    def layout_designer(request: Request, company_id: int | None = None,
                        env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        env.check_access("res.company", "read")
        token = getattr(request.state, "csrf_token", "")
        return HTMLResponse(_layout.render_designer(env, company_id, token))

    def _login_redirect(request: Request):
        from fastapi.responses import RedirectResponse
        next_url = str(request.url.path)
        if request.url.query:
            next_url += "?" + request.url.query
        return RedirectResponse(f"/login?next={next_url}", status_code=302)

    @app.get("/web/report/layout/designer", response_class=HTMLResponse)
    def layout_designer_page(request: Request, company_id: int | None = None,
                             env: Environment = Depends(get_env)):
        if env.uid is None:
            return _login_redirect(request)
        try:
            env.check_access("res.company", "read")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        token = getattr(request.state, "csrf_token", "")
        return HTMLResponse(_layout.render_designer_page(env, company_id, token))

    @app.get("/report/layout/designer/page", response_class=HTMLResponse)
    def layout_designer_page_legacy(company_id: int | None = None):
        """Permanent redirect — designer lives under /web/ in the app shell."""
        from fastapi.responses import RedirectResponse
        qs = f"?company_id={company_id}" if company_id else ""
        return RedirectResponse(f"/web/report/layout/designer{qs}", status_code=301)

    @app.get("/report/layout/preview-live", response_class=HTMLResponse)
    def preview_live(env: Environment = Depends(get_env), company_id: int | None = None,
                     layout: str = "", paper: str = "", color: str = "",
                     secondary: str = "", font: str = "", logo: str = ""):
        """Live preview with unsaved override values (used by the designer JS)."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        env.check_access("res.company", "read")
        overrides = {"layout": layout, "paper": paper, "color": color,
                     "secondary": secondary, "font": font, "logo": logo}
        return HTMLResponse(
            _layout.render_layout_preview(env, company_id, overrides=overrides, inline=True))

    @app.post("/report/layout/designer/save")
    def layout_designer_save(payload: dict = Body(default={}),
                             env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        cid = payload.get("company_id")
        if not cid or not env["res.company"].search([("id", "=", int(cid))], limit=1):
            raise HTTPException(status_code=404, detail="Company not found")
        vals = {k: payload[k] for k in
                ("document_layout", "paper_format", "primary_color", "logo_url",
                 "secondary_color", "google_font")
                if k in payload}
        try:
            env["res.company"].browse(int(cid)).write(vals)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        env.conn.commit()  # pooled connection is not autocommit
        return {"ok": True}
