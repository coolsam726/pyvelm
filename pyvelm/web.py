"""FastAPI app factory + generic read endpoints.

This is the thin async boundary in front of the sync ORM. The app is
parameterized by a loaded `Registry` and a Postgres connection pool;
each request grabs a connection, wraps it in an `Environment`, runs the
handler, and returns the connection to the pool.

Slice A surface (read-only):
  GET /api/views/{module}/{name}
  GET /api/records?model=...&domain=...&fields=...&limit=...&offset=...

Mutation endpoints come in Slice B. Auth is out of scope here — the
intended deployment puts a real authentication layer in front.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

import base64
import binascii

from fastapi import (
    Body, Depends, FastAPI, File, Form, HTTPException, Query, Request,
    UploadFile,
)
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("pyvelm.web")

from .env import Environment
from .fields import Many2many, Many2one, One2many
from .registry import Registry


def _form_parent_nav(request: Request) -> dict:
    """Parent-view query params on form URLs (ref, bc stack, filters)."""
    q = request.query_params
    ref_key = (q.get("ref") or q.get("list") or "").strip()
    ref_module: str | None = None
    ref_name: str | None = None
    if "/" in ref_key:
        ref_module, ref_name = ref_key.split("/", 1)
    page_raw = q.get("page", "")
    page_size_raw = q.get("page_size", "")
    try:
        page = int(page_raw) if page_raw != "" else None
    except ValueError:
        page = None
    try:
        page_size = int(page_size_raw) if page_size_raw != "" else None
    except ValueError:
        page_size = None
    from .render import parse_bc_param

    bc_stack = parse_bc_param(q.get("bc"))
    return {
        "list_module": ref_module or None,
        "list_name": ref_name or None,
        "list_search": q.get("search") or "",
        "list_order": q.get("order") or "",
        "list_filters": q.get("filters") or "",
        "group_by": q.get("group_by") or "",
        "page": page,
        "page_size": page_size,
        "bc_stack": bc_stack,
    }


def _form_list_nav(request: Request) -> dict:
    """Backward-compatible alias for :func:`_form_parent_nav`."""
    return _form_parent_nav(request)


def _display_value(record) -> str:
    """Best-effort short label for a Many2one render.

    Tries `display_name` (Odoo convention) then `name`, then `str(id)`.
    Doesn't trigger a search — just reads from the cache via the
    descriptor, accepting that this hits the DB if the cache misses.
    """
    if not record:
        return ""
    # Avoid `record.id` (descriptor) because it can trigger `_read` and
    # therefore a model ACL check. We sometimes need a label for a related
    # record the caller cannot read; in that case we still want to fall back
    # to the referenced primary key.
    raw_id = None
    try:
        raw_id = record._ids[0] if getattr(record, "_ids", None) else None
    except Exception:  # noqa: BLE001
        raw_id = None
    for attr in ("display_name", "name"):
        if attr in record._fields:
            try:
                value = getattr(record, attr)
                if value is not None:
                    return str(value)
            except PermissionError:
                # Relationship labels are frequently needed even when the
                # current user has no access to the related model (e.g.
                # showing company name on a lead row). Allow a narrow
                # fallback: fetch the label for this already-referenced id
                # under sudo, without granting broader model access.
                try:
                    su = record.env.sudo()[record._name].browse(raw_id or record.id)
                    su.ensure_one()
                    value = getattr(su, attr, None)
                    if value is not None:
                        return str(value)
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001
                pass
    if raw_id is not None:
        return str(raw_id)
    # Last resort: may trigger ACL, but we have no other handle.
    return str(record.id)


def _form_save_toast_payload(record, *, created: bool = False) -> dict[str, str]:
    """Toast body for ``HX-Trigger: pv-toast`` after a successful form save."""
    label = _display_value(record) if record else ""
    if created:
        message = f"Created {label}." if label else "Record created."
        title = "Created"
    else:
        message = f"Saved {label}." if label else "Changes saved."
        title = "Saved"
    return {"message": message, "variant": "success", "title": title}


def _form_save_toast_headers(record, *, created: bool = False) -> dict[str, str]:
    """``HX-Trigger`` header so the layout shows a success toast after save."""
    return {
        "HX-Trigger": json.dumps({
            "pv-toast": _form_save_toast_payload(record, created=created),
        }),
    }


def _form_in_dialog(request: Request) -> bool:
    """True when the client is loading/saving inside ``PvDialog``."""
    return request.headers.get("X-PV-Dialog") == "1"


def serialize_record(record, fields: list[str] | None = None) -> dict[str, Any]:
    """Convert a singleton recordset into a JSON-friendly dict.

    Many2one => [id, display_value]. One2many/Many2many => list of ids.
    Scalars pass through. `id` is always included.

    Private fields (``Field.private == True``) are *always* skipped — no
    JSON path on the framework can hand a bcrypt hash to a client, even
    when the caller asks for the field by name. Programmatic access
    inside the ORM (the descriptor) still reaches them.
    """
    record.ensure_one()
    model_cls = type(record)
    if fields is None:
        fields = [
            f for f, fld in model_cls._fields.items()
            if fld.is_stored and not fld.private
        ]
    out: dict[str, Any] = {"id": record.id}
    for fname in fields:
        if fname == "id":
            continue  # already in `out`, treat as a no-op rather than an error
        if fname not in model_cls._fields:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown field {fname!r} on {model_cls._name}",
            )
        field = model_cls._fields[fname]
        if field.private:
            # Honor the privacy flag even when the caller asked for the
            # field explicitly. Defense in depth — keeps Password and
            # any future private fields out of HTTP responses by
            # construction, not by convention.
            continue
        value = getattr(record, fname)
        if isinstance(field, Many2one):
            if not value:
                out[fname] = None
            else:
                out[fname] = [value.id, _display_value(value)]
        elif isinstance(field, (One2many, Many2many)):
            out[fname] = list(value._ids)
        else:
            out[fname] = value
    return out


def serialize_records(records, fields: list[str] | None = None) -> list[dict]:
    return [serialize_record(r, fields) for r in records]


def _parse_domain(domain_json: str) -> list:
    if not domain_json:
        return []
    try:
        domain = json.loads(domain_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid domain JSON: {e}")
    if not isinstance(domain, list):
        raise HTTPException(status_code=400, detail="Domain must be a JSON array")
    return [tuple(leaf) for leaf in domain]


def create_app(
    registry: Registry,
    database_or_pool: Any,
    module_roots: list | None = None,
    *,
    runtime_env: str | None = None,
) -> FastAPI:
    """Build the FastAPI app bound to a loaded registry and database pool.

    Pass a :class:`~pyvelm.database.Database` (v1+) or a legacy pool object
    exposing ``connection()`` (psycopg_pool or :class:`~pyvelm.database.PoolFacade`).
    Each request checks out a connection, makes an Environment, and returns
    it on exit.

    `module_roots` is the same list passed to `loader.load_and_install`
    so the Apps catalog page can re-discover the disk-side manifests.
    Boot-time install only applies **base** and **admin** on a fresh DB;
    other modules are installed from **Apps**, `pyvelm db migrate --module …`,
    or `pyvelm db migrate --all`.
    Optional — if omitted, the catalog page reports "no roots configured"
    instead of crashing.

    ``runtime_env`` (or ``PYVELM_ENV``) selects development vs production:
    API docs, cookie ``Secure`` flags, etc. See :mod:`pyvelm.runtime`.

    `database_or_pool` is typed `Any` — see :mod:`pyvelm.database.Database`."""
    from .database import Database
    from .policies import register_builtin_policies
    from .runtime import cookie_options, get_runtime_env, is_development

    if isinstance(database_or_pool, Database):
        database = database_or_pool
        pool = database.pool
    else:
        database = None
        pool = database_or_pool

    register_builtin_policies()
    env_mode = get_runtime_env(runtime_env)
    dev = is_development(env_mode)
    auth_cookie = cookie_options(env=env_mode)
    from pyvelm.session_auth import SESSION_COOKIE_MAX_AGE

    session_cookie = {**auth_cookie, "max_age": SESSION_COOKIE_MAX_AGE}

    app = FastAPI(
        title="pyvelm",
        docs_url="/docs" if dev else None,
        redoc_url="/redoc" if dev else None,
        openapi_url="/openapi.json" if dev else None,
    )
    app.state.module_roots = list(module_roots or [])
    app.state.pyvelm_env = env_mode
    app.state.auth_cookie_options = auth_cookie
    app.state.session_cookie_options = session_cookie
    app.state.registry = registry
    app.state.database = database
    app.state.pool = pool

    from .database_routing import (
        DATABASE_COOKIE,
        configure_app_databases,
        list_selectable_databases,
        routing_enabled,
    )

    if database is not None:
        configure_app_databases(
            app, database, registry, app.state.module_roots,
        )
    if database is not None and routing_enabled(app):
        from .database_routing import DatabaseSelectorMiddleware

        app.add_middleware(DatabaseSelectorMiddleware)

    _REQUIRED_MODELS = ("res.users", "ir.ui.view")
    missing = [m for m in _REQUIRED_MODELS if m not in registry]
    if missing:
        raise RuntimeError(
            f"Registry is missing required models: {missing}. "
            "Call loader.load_and_install(BUILTIN_MODULE_ROOTS + [...], env) "
            "before create_app(). If you use uvicorn --reload, upgrade pyvelm "
            "or restart without reload once to verify."
        )

    # ── CSRF: double-submit cookie ──
    # We mint a random `pyvelm_csrf` cookie on the first GET that
    # doesn't carry one. Every unsafe method (POST/PUT/PATCH/DELETE)
    # must echo the cookie value back either as the `X-CSRF-Token`
    # header (HTMX requests do this automatically via the layout
    # listener) or as the `_csrf` form field (the login template
    # embeds it). The cookie is NOT HttpOnly because JS must read it
    # for the header path; same-site=Lax keeps it from riding cross-
    # origin POSTs.
    #
    # Machine clients using HTTP Basic auth typically don't carry
    # cookies, so they're transparently skipped — the check only
    # fires when *some* cookie is present.
    _CSRF_COOKIE = "pyvelm_csrf"
    _CSRF_HEADER = "X-CSRF-Token"
    _CSRF_FORM_FIELD = "_csrf"
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def _csrf_reject(detail: str) -> Response:
        return Response(
            content=detail,
            status_code=403,
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    class CsrfMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            cookie_token = request.cookies.get(_CSRF_COOKIE)

            # Make the token available to handlers via request.state so
            # template renderers can embed it in `<input type="hidden">`
            # without re-fetching cookies. For first-time visitors we
            # mint the value here too — the cookie is then set on the
            # response below.
            request.state.csrf_token = cookie_token or secrets.token_urlsafe(32)

            # Skip CSRF on Basic-auth requests — by definition the
            # attacker can't forge the Authorization header in a
            # CSRF attack, so the double-submit cookie buys nothing
            # there. Machine clients / scripts use Basic.
            auth_header = request.headers.get("authorization", "")
            is_basic_auth = auth_header.startswith("Basic ")

            if (
                request.method not in _SAFE_METHODS
                and request.cookies
                and not is_basic_auth
            ):
                if not cookie_token:
                    return _csrf_reject("CSRF token missing.")
                header_token = request.headers.get(_CSRF_HEADER)
                ok = header_token == cookie_token
                if not ok:
                    # Query-string fallback. Used by multipart HTML
                    # forms (file uploads) whose body the middleware
                    # deliberately doesn't buffer — the form template
                    # renders ``action="…?_csrf={{ csrf_token }}"``.
                    qs_token = request.query_params.get(_CSRF_FORM_FIELD)
                    if qs_token and qs_token == cookie_token:
                        ok = True
                if not ok:
                    # Form-encoded body fallback. We only inspect
                    # bodies that are actually form-urlencoded so
                    # later multipart uploads don't get buffered into
                    # memory by the middleware.
                    ct = request.headers.get("content-type", "")
                    if ct.startswith("application/x-www-form-urlencoded"):
                        body = await request.body()
                        from urllib.parse import parse_qs

                        parsed = parse_qs(body.decode("latin-1"))
                        form_token = (parsed.get(_CSRF_FORM_FIELD) or [""])[0]
                        ok = form_token == cookie_token

                        # Restore the consumed receive stream so the
                        # downstream handler can parse the body itself.
                        async def receive() -> dict:
                            return {
                                "type": "http.request",
                                "body": body,
                                "more_body": False,
                            }

                        request._receive = receive
                    if not ok:
                        return _csrf_reject("CSRF token invalid.")

            response = await call_next(request)

            # Mint a cookie on every response that didn't ride one in.
            # 30-day max-age — only refreshes on logout / user clears.
            if not cookie_token:
                response.set_cookie(
                    _CSRF_COOKIE,
                    request.state.csrf_token,
                    max_age=60 * 60 * 24 * 30,
                    samesite="lax",
                    httponly=False,
                    path="/",
                )
            return response

    app.add_middleware(CsrfMiddleware)

    # Prevent browsers from caching authenticated pages.  Without this
    # header the back-button serves a stale cached copy after logout.
    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            path = request.url.path
            # Apply to all /web/ HTML routes except static assets.
            if path.startswith("/web/") and not path.startswith("/web/static"):
                response.headers["Cache-Control"] = (
                    "no-store, no-cache, must-revalidate, private"
                )
                response.headers["Pragma"] = "no-cache"
            return response

    app.add_middleware(NoCacheMiddleware)

    def _wants_html_error_page(request: Request) -> bool:
        """Browser page navigations under ``/web/`` get a styled HTML body."""
        if request.headers.get("HX-Request") == "true":
            return False
        if request.url.path.startswith("/api/"):
            return False
        if request.method == "GET" and request.url.path.startswith("/web/"):
            return True
        accept = request.headers.get("accept", "")
        return "text/html" in accept

    def _render_styled_error(
        request: Request,
        status_code: int,
        *,
        detail: str | None = None,
        message: str | None = None,
        retry_after: int | None = None,
        extra_headers: dict | None = None,
    ) -> Response:
        """Build a styled HTML error page or fall back to the plain default.

        Browsers hitting ``/web/`` pages get the rendered card; API / HTMX
        / JSON callers get the same status code with a small text body so
        clients don't have to scrape HTML for the error message.
        """
        wants_html = _wants_html_error_page(request)
        headers = dict(extra_headers or {})
        if retry_after is not None:
            headers.setdefault("Retry-After", str(retry_after))
        if not wants_html:
            body = detail or message or ""
            if not body:
                from http import HTTPStatus

                try:
                    body = HTTPStatus(status_code).phrase
                except ValueError:
                    body = "Error"
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
            return Response(content=body, status_code=status_code, headers=headers)

        from pyvelm.request_env import apply_request_scope
        from .render import render_error_page

        with _active_pool(request).connection() as conn:
            env = Environment(conn, registry=_active_registry(request), uid=None)
            env = apply_request_scope(
                env,
                request,
                resolve_session=_resolve_user_from_session,
                resolve_basic=_resolve_user_from_basic,
            )
            html = render_error_page(
                env,
                status_code=status_code,
                message=message,
                detail=detail,
                current_path=str(request.url.path),
                retry_after=retry_after,
            )
        return HTMLResponse(html, status_code=status_code, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    def _http_exception(request: Request, exc: StarletteHTTPException):
        """Catch every ``HTTPException`` (incl. router 404s).

        401 and 403 already have richer handlers (login redirect /
        access-denied page); 404+ get the styled error card for browsers.
        Pass-through to the styled page only for statuses that aren't
        already specialised.
        """
        status = exc.status_code
        if status == 401:
            # Mirror the existing flow: redirect browsers to /login,
            # 401 with WWW-Authenticate for API callers.
            return _auth_required_response(request)
        if status == 403:
            # The PermissionError handler already covers domain-level
            # denials. Bare 403 HTTPException uses the generic error page.
            pass
        detail = exc.detail if isinstance(exc.detail, str) else None
        retry_after = None
        extra_headers: dict = {}
        if exc.headers:
            extra_headers.update(exc.headers)
            if "Retry-After" in exc.headers:
                try:
                    retry_after = int(exc.headers["Retry-After"])
                except (TypeError, ValueError):
                    retry_after = None
        return _render_styled_error(
            request,
            status,
            detail=detail,
            retry_after=retry_after,
            extra_headers=extra_headers,
        )

    @app.exception_handler(Exception)
    def _unhandled_exception(request: Request, exc: Exception):
        """Last-resort handler: turn an uncaught error into a styled 500.

        Logs the traceback so the operator can diagnose; the rendered
        page only shows the exception's ``str`` (no traceback in the
        browser). API / JSON callers get the same status + a short
        text body.
        """
        log.exception(
            "unhandled exception on %s %s", request.method, request.url.path
        )
        return _render_styled_error(
            request,
            500,
            detail=str(exc) or exc.__class__.__name__,
        )

    @app.exception_handler(PermissionError)
    def _permission_error(request, exc):
        msg = str(exc)
        is_anonymous = "anonymous" in msg or "uid=None" in msg
        is_htmx = request.headers.get("HX-Request") == "true"
        wants_html = _wants_html_error_page(request)
        # Not logged in: send them to sign in (or 401 the API caller).
        if is_anonymous:
            if is_htmx or wants_html:
                return _auth_required_response(request)
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="pyvelm"'},
                content=msg,
            )
        # Authenticated but denied: render the styled page for browsers,
        # plain text for API / HTMX callers.
        if wants_html:
            from pyvelm.request_env import apply_request_scope
            from .render import render_access_denied_page

            with _active_pool(request).connection() as conn:
                env = Environment(conn, registry=_active_registry(request), uid=None)
                env = apply_request_scope(
                    env,
                    request,
                    resolve_session=_resolve_user_from_session,
                    resolve_basic=_resolve_user_from_basic,
                )
                html = render_access_denied_page(
                    env, detail=msg, current_path=str(request.url.path)
                )
            return HTMLResponse(html, status_code=403)
        return Response(status_code=403, content=msg)

    # Static assets shipped inside the package (CSS, eventually images).
    from .render import STATIC_DIR

    app.mount(
        "/web/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="pyvelm-static",
    )

    _SESSION_COOKIE = "pyvelm_session"
    _COMPANY_COOKIE = "pyvelm_company"

    def _resolve_user_from_session(env: Environment, token: str | None) -> int | None:
        """Return uid for a valid session token, or None."""
        from pyvelm.session_auth import resolve_session_uid

        return resolve_session_uid(env, token)

    def _resolve_user_from_basic(
        env: Environment, header_value: str | None
    ) -> int | None:
        """Parse an HTTP Basic header and return the authenticated uid.

        Returns None for missing / invalid / failed-login cases. Callers
        decide whether to reject; the ACL layer will deny most things
        for an anonymous uid.
        """
        if not header_value or not header_value.lower().startswith("basic "):
            return None
        try:
            raw = base64.b64decode(header_value.split(None, 1)[1])
            login, password = raw.decode("utf-8", errors="ignore").split(":", 1)
        except (binascii.Error, ValueError):
            return None
        if "res.users" not in env.registry:
            return None
        # sudo: look up the user without ACL (request env stays enforced).
        users = env.sudo()["res.users"].search(
            [("login", "=", login), ("active", "=", True)],
            limit=1,
        )
        if not users:
            return None
        user = users
        user.ensure_one()
        if not user.check_password(password):
            return None
        return user.id

    def get_env(request: Request):
        from pyvelm.database_routing import get_request_pool, get_request_registry
        from pyvelm.request_env import apply_request_scope

        active_registry = get_request_registry(app, request)
        active_pool = get_request_pool(app, request)
        with active_pool.connection() as conn:
            env = Environment(conn, registry=active_registry, uid=None)
            env = apply_request_scope(
                env,
                request,
                resolve_session=_resolve_user_from_session,
                resolve_basic=_resolve_user_from_basic,
            )
            yield env

    def _active_pool(request: Request):
        from pyvelm.database_routing import get_request_pool

        return get_request_pool(app, request)

    def _active_registry(request: Request):
        from pyvelm.database_routing import get_request_registry

        return get_request_registry(app, request)

    def _load_view(env, module: str, name: str):
        from .render import _load_ui_view

        if "ir.ui.view" not in registry:
            raise HTTPException(status_code=503, detail="No ir.ui.view model loaded")
        rec = _load_ui_view(env, module, name)
        if not rec:
            raise HTTPException(
                status_code=404, detail=f"View {module}/{name} not found"
            )
        return rec

    def _login_redirect(request: Request) -> RedirectResponse:
        """Redirect to /login preserving the originally-requested URL."""
        next_url = str(request.url.path)
        if request.url.query:
            next_url += "?" + request.url.query
        return RedirectResponse(f"/login?next={next_url}", status_code=302)

    def _auth_required_response(request: Request) -> Response:
        """Return the right shape of "you must log in" for the caller.

        HTMX requests get an `HX-Redirect` header so the client-side
        library does a full-page navigation to /login instead of trying
        to swap the redirect's HTML into the page. Plain browser
        navigations get a 302 redirect. JSON callers get a 401.
        """
        if request.headers.get("HX-Request") == "true":
            next_url = str(request.url.path)
            if request.url.query:
                next_url += "?" + request.url.query
            return Response(
                status_code=204,
                headers={"HX-Redirect": f"/login?next={next_url}"},
            )
        accept = request.headers.get("accept", "")
        if "application/json" in accept and "text/html" not in accept:
            raise HTTPException(status_code=401, detail="Authentication required")
        return _login_redirect(request)

    @app.get("/api/views/{module}/{name}")
    def get_view(module: str, name: str, env: Environment = Depends(get_env)):
        from .views import resolve_arch

        rec = _load_view(env, module, name)
        return {
            "id": rec.id,
            "module": rec.module,
            "name": rec.name,
            "model": rec.model,
            "view_type": rec.view_type,
            # Always resolve through the inheritance chain — the user
            # gets the same answer whether they asked for the base view
            # or an extension that points at it.
            "arch": resolve_arch(rec),
        }

    @app.get("/web/views/{module}/{name}", response_class=HTMLResponse)
    def web_view_page(
        module: str,
        name: str,
        request: Request,
        page: int = Query(default=0, ge=0),
        page_size: int = Query(default=10, ge=1, le=200),
        search: str = Query(default=""),
        order: str = Query(default=""),
        filters: str = Query(default=""),
        group_by: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import (
            parse_bc_param,
            render_dashboard_page,
            render_graph_page,
            render_kanban_page,
            render_list_page,
        )

        rec = _load_view(env, module, name)
        path = str(request.url.path)
        bc_stack = parse_bc_param(request.query_params.get("bc"))
        if rec.view_type == "dashboard":
            return HTMLResponse(
                render_dashboard_page(rec, env, current_path=path)
            )
        if rec.view_type == "list":
            return HTMLResponse(
                render_list_page(
                    rec,
                    env,
                    page=page,
                    page_size=page_size,
                    search=search,
                    order=order,
                    filters=filters,
                    group_by=group_by,
                    bc_stack=bc_stack,
                    current_path=path,
                )
            )
        if rec.view_type == "kanban":
            return HTMLResponse(
                render_kanban_page(
                    rec,
                    env,
                    page=page,
                    page_size=page_size,
                    search=search,
                    order=order,
                    filters=filters,
                    group_by=group_by,
                    bc_stack=bc_stack,
                    current_path=path,
                )
            )
        if rec.view_type == "graph":
            return HTMLResponse(
                render_graph_page(
                    rec,
                    env,
                    search=search,
                    filters=filters,
                    current_path=path,
                )
            )
        if rec.view_type == "pivot":
            from .render import render_pivot_page

            return HTMLResponse(
                render_pivot_page(
                    rec,
                    env,
                    search=search,
                    filters=filters,
                    current_path=path,
                )
            )
        # Form views land on /record/{id}; bare URL is meaningless.
        raise HTTPException(
            status_code=501,
            detail=(
                f"view_type {rec.view_type!r} has no top-level page; "
                f"form views use /record/{{id}} instead"
            ),
        )

    @app.get("/web/records/{module}/{name}", response_class=HTMLResponse)
    def web_view_rows(
        module: str,
        name: str,
        request: Request,
        page: int = Query(default=0, ge=0),
        page_size: int = Query(default=10, ge=1, le=200),
        search: str = Query(default=""),
        order: str = Query(default=""),
        filters: str = Query(default=""),
        group_by: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        """HTML fragment endpoint used by HTMX `load more` swaps."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .render import parse_bc_param, render_kanban_rows, render_list_rows

        rec = _load_view(env, module, name)
        bc_stack = parse_bc_param(request.query_params.get("bc"))
        if rec.view_type == "list":
            return HTMLResponse(
                render_list_rows(
                    rec,
                    env,
                    page=page,
                    page_size=page_size,
                    search=search,
                    order=order,
                    filters=filters,
                    group_by=group_by,
                    bc_stack=bc_stack,
                )
            )
        if rec.view_type == "kanban":
            return HTMLResponse(
                render_kanban_rows(
                    rec,
                    env,
                    page=page,
                    page_size=page_size,
                    search=search,
                    order=order,
                    filters=filters,
                    group_by=group_by,
                    bc_stack=bc_stack,
                )
            )
        raise HTTPException(
            status_code=501,
            detail=f"Renderer for view_type {rec.view_type!r} not yet shipped",
        )

    def _coerce_json_vals(model_name: str, vals: dict) -> dict:
        """Validate keys exist on the model. Type coercion is delegated
        to each field's `to_sql_param`, which the ORM already calls."""
        cls = registry[model_name]
        unknown = [k for k in vals if k not in cls._fields]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown field(s) on {model_name}: {unknown}",
            )
        return vals

    @app.post("/api/records", status_code=201)
    def create_record(
        model: str = Query(...),
        vals: dict = Body(...),
        env: Environment = Depends(get_env),
    ):
        if model not in registry:
            raise HTTPException(404, f"Unknown model {model!r}")
        clean = _coerce_json_vals(model, vals)
        with env.transaction():
            rec = env[model].create(clean)
        return serialize_record(rec)

    @app.patch("/api/records/{record_id}")
    def write_record(
        record_id: int,
        model: str = Query(...),
        vals: dict = Body(...),
        env: Environment = Depends(get_env),
    ):
        if model not in registry:
            raise HTTPException(404, f"Unknown model {model!r}")
        rec = env[model].browse(record_id)
        if not env[model].search([("id", "=", record_id)]):
            raise HTTPException(404, f"{model}({record_id}) not found")
        clean = _coerce_json_vals(model, vals)
        with env.transaction():
            rec.write(clean)
        # Reread so the response reflects post-write state (including any
        # stored compute fields that fired).
        env.cache.invalidate(model_name=model, ids=[record_id])
        return serialize_record(env[model].browse(record_id))

    @app.delete("/api/records/{record_id}", status_code=204, response_class=Response)
    def delete_record(
        record_id: int,
        model: str = Query(...),
        env: Environment = Depends(get_env),
    ):
        if model not in registry:
            raise HTTPException(404, f"Unknown model {model!r}")
        rec = env[model].browse(record_id)
        if not env[model].search([("id", "=", record_id)]):
            raise HTTPException(404, f"{model}({record_id}) not found")
        with env.transaction():
            rec.unlink()
        return Response(status_code=204)

    # ---- Many2one combobox endpoints ----
    #
    # Drive the searchable / create-on-the-fly relationship widget.
    # Both endpoints are authenticated (env.uid required) but rely on
    # the normal ORM ACL underneath — a user without read on the
    # comodel will see an empty list; a user without create gets 403
    # on quick-create.

    @app.get("/api/m2o/search")
    def m2o_search(
        model: str = Query(...),
        q: str = Query(default=""),
        limit: int = Query(default=10, ge=1, le=100),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if model not in registry:
            raise HTTPException(status_code=404, detail=f"Unknown model {model!r}")
        Model = env[model]
        q = q.strip()
        # Search the comodel by `name` ILIKE when available; otherwise
        # fall back to whatever stored Char field exists.
        cls = registry[model]
        from .fields import Char, Text

        text_field = None
        if "name" in cls._fields and isinstance(cls._fields["name"], (Char, Text)):
            text_field = "name"
        else:
            for fname, field in cls._fields.items():
                if isinstance(field, (Char, Text)) and field.is_stored:
                    text_field = fname
                    break
        domain = []
        if q and text_field is not None:
            domain.append((text_field, "ilike", f"%{q}%"))
        recs = Model.search(domain, limit=limit, order='"id" ASC')
        return {
            "results": [{"id": r.id, "label": _display_value(r)} for r in recs],
        }

    @app.post("/api/m2o/quick-create")
    def m2o_quick_create(
        body: dict = Body(...),
        env: Environment = Depends(get_env),
    ):
        """Quick-create a comodel record with only `name` set.

        Returns 400 if the comodel has additional required fields the
        widget can't supply — the client falls back to navigating to
        the comodel's form view's `/new` page.
        """
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        model = body.get("model")
        name = (body.get("name") or "").strip()
        if not model or model not in registry:
            raise HTTPException(status_code=404, detail=f"Unknown model {model!r}")
        if not name:
            raise HTTPException(status_code=400, detail="Missing 'name'")
        cls = registry[model]
        # Check for other required fields that aren't `name`. If any
        # exist without a default, we can't quick-create — surface a
        # 400 so the client can redirect to "Create and edit".
        from .fields import Many2many

        missing_required: list[str] = []
        for fname, field in cls._fields.items():
            if not field.required or fname == "name":
                continue
            if field.compute:
                continue
            if isinstance(field, Many2many):
                continue
            if field.default is not None:
                continue
            missing_required.append(fname)
        if missing_required:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot quick-create {model!r}: requires "
                    f"{sorted(missing_required)}. Use Create and edit instead."
                ),
            )
        with env.transaction():
            rec = env[model].create({"name": name})
        return {"id": rec.id, "label": _display_value(rec)}

    @app.get("/api/records")
    def list_records(
        model: str,
        domain: str = Query(default="[]"),
        fields: str = Query(default=""),
        limit: int | None = Query(default=None),
        offset: int = Query(default=0),
        order: str | None = Query(default=None),
        env: Environment = Depends(get_env),
    ):
        if model not in registry:
            raise HTTPException(status_code=404, detail=f"Unknown model {model!r}")
        domain_parsed = _parse_domain(domain)
        field_list = [f.strip() for f in fields.split(",") if f.strip()] or None
        Model = env[model]
        recs = Model.search(domain_parsed, limit=limit, offset=offset, order=order)
        return {
            "model": model,
            "count": len(recs),
            "records": serialize_records(recs, field_list),
        }

    # ---- HTMX inline-edit row endpoints ----
    # Each returns a <tr> fragment. Flow: list page renders rows via
    # list_row.html with Edit/Delete buttons; Edit hx-gets /edit and
    # swaps in list_row_edit.html; Save hx-posts here and the response
    # is the updated display row; Cancel hx-gets the unmodified display
    # row; Delete unlinks and returns an empty body so hx-swap="outerHTML"
    # removes the <tr>; "+ New" hx-gets /new for a blank edit row at the
    # top of the table.

    def _load_record(env, view, record_id: int):
        Model = env[view.model]
        if not Model.search([("id", "=", record_id)]):
            raise HTTPException(404, f"{view.model}({record_id}) not found")
        return Model.browse(record_id)

    def _row_validation_error(view, rec, env, errors: dict) -> Response:
        """Build the 422 response for an inline-row save with parse-side
        errors. Re-renders the row in edit mode so the user keeps typing
        and emits an `HX-Trigger` event the layout routes to pvAlert."""
        import json as _json
        from .render import render_list_row, render_new_row

        if rec is None:
            body = render_new_row(view, env)
        else:
            body = render_list_row(view, rec, env, mode="edit")
        message = "; ".join(f"{k}: {v}" for k, v in errors.items())
        return HTMLResponse(
            body,
            status_code=422,
            headers={
                "HX-Trigger": _json.dumps({"pv-validation-error": message}),
            },
        )

    @app.get("/web/records/{module}/{name}/new", response_class=HTMLResponse)
    def web_row_new(
        module: str, name: str, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_new_row

        view = _load_view(env, module, name)
        return HTMLResponse(render_new_row(view, env))

    @app.get(
        "/web/records/{module}/{name}/row/{record_id}", response_class=HTMLResponse
    )
    def web_row_display(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    @app.get(
        "/web/records/{module}/{name}/row/{record_id}/edit", response_class=HTMLResponse
    )
    def web_row_edit(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        return HTMLResponse(render_list_row(view, rec, env, mode="edit"))

    @app.post(
        "/web/records/{module}/{name}/row/{record_id}", response_class=HTMLResponse
    )
    async def web_row_save(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form, env)
        if errors:
            # Inline rows don't have room for per-cell error messages;
            # surface the first problem via a 422 + HX-Trigger event so
            # the layout's pvAlert handler shows a toast and the edit
            # row stays open.
            return _row_validation_error(view, rec, env, errors)
        with env.transaction():
            rec.write(vals)
        # Reread for any computed-field follow-on values.
        env.cache.invalidate(model_name=view.model, ids=[record_id])
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    @app.delete(
        "/web/records/{module}/{name}/row/{record_id}", response_class=HTMLResponse
    )
    def web_row_delete(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        with env.transaction():
            rec.unlink()
        return HTMLResponse("")

    @app.post("/web/records/{module}/{name}/reorder")
    async def web_row_reorder(
        module: str,
        name: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Persist a new row ordering for a list view that declared
        `arch["sequence"] = "<field>"`. Body: `{ids: [42, 17, 9, ...]}`
        in the desired top-to-bottom order. We rewrite the named field
        to monotonically-increasing multiples of 10 so future inserts
        can slot between existing rows without a global renumber."""
        if env.uid is None:
            return _auth_required_response(request)
        from .views import resolve_arch

        view = _load_view(env, module, name)
        arch = resolve_arch(view)
        seq_field = arch.get("sequence")
        if not seq_field:
            raise HTTPException(
                status_code=400,
                detail=f"View {module}/{name} doesn't declare a sequence field.",
            )
        Model = env[view.model]
        cls = env.registry[view.model]
        if seq_field not in cls._fields:
            raise HTTPException(
                status_code=400,
                detail=f"{view.model} has no field {seq_field!r}",
            )
        try:
            payload = await request.json()
            ids = [int(i) for i in payload.get("ids", [])]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Malformed payload")
        if not ids:
            return Response(status_code=204)

        with env.transaction():
            for position, rid in enumerate(ids):
                rec = Model.browse(rid)
                if Model.search([("id", "=", rid)]):
                    rec.write({seq_field: (position + 1) * 10})
        return Response(status_code=204)

    @app.post("/web/records/{module}/{name}/kanban/move")
    async def web_kanban_move(
        module: str,
        name: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Persist a grouped kanban drag-drop.

        Body: ``{group_by, column_key, ids: […]}`` where ``ids`` is the
        destination column's card order (top to bottom). Updates the
        grouping field for every card in the column and, when the view
        arch declares ``sequence``, rewrites sequence values.
        """
        if env.uid is None:
            return _auth_required_response(request)
        from .render import (
            _kanban_group_write_value,
            _kanban_resolve_group_field,
        )
        from .views import resolve_arch

        view = _load_view(env, module, name)
        if view.view_type != "kanban":
            raise HTTPException(
                status_code=400,
                detail=f"{module}/{name} is not a kanban view.",
            )
        arch = resolve_arch(view)
        try:
            payload = await request.json()
            group_by = str(payload.get("group_by", ""))
            column_key = payload.get("column_key")
            ids = [int(i) for i in payload.get("ids", [])]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Malformed payload")

        try:
            group_field = _kanban_resolve_group_field(view, arch, group_by)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not group_field:
            raise HTTPException(
                status_code=400,
                detail="Kanban is not grouped; drag-drop is unavailable.",
            )

        Model = env[view.model]
        cls = env.registry[view.model]
        if group_field not in cls._fields:
            raise HTTPException(
                status_code=400,
                detail=f"{view.model} has no field {group_field!r}",
            )

        seq_field = arch.get("sequence")
        if seq_field and seq_field not in cls._fields:
            seq_field = None

        group_val = _kanban_group_write_value(cls, group_field, column_key)
        with env.transaction():
            for position, rid in enumerate(ids):
                if not Model.search([("id", "=", rid)]):
                    continue
                vals = {group_field: group_val}
                if seq_field:
                    vals[seq_field] = (position + 1) * 10
                Model.browse(rid).write(vals)
        return Response(status_code=204)

    @app.post("/web/records/{module}/{name}", response_class=HTMLResponse)
    async def web_row_create(
        module: str,
        name: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        cls = env.registry[view.model]
        form = await request.form()
        vals, errors = parse_form_vals(cls, form, env)
        if errors:
            return _row_validation_error(view, None, env, errors)
        with env.transaction():
            rec = env[view.model].create(vals)
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    # ---- form-view routes ----
    # Single-record screen. Display / edit / new are three modes of the
    # same shell template; HTMX swaps the inner #pyvelm-form-shell on
    # mode transitions so action buttons get repainted along with the
    # form body.

    def _require_form_view(rec):
        if rec.view_type != "form":
            raise HTTPException(400, f"View {rec.module}.{rec.name} is not a form view")
        return rec

    @app.get("/web/views/{module}/{name}/new", response_class=HTMLResponse)
    def web_form_new(
        module: str,
        name: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        if not env.has_access(view.model, "create"):
            raise PermissionError(f"You cannot create {view.model} records.")
        # Query params named after declared fields prefill the new
        # record's defaults — used by the O2m inline-Add link to
        # carry the parent FK into the child form.
        model_cls = env.registry[view.model]
        prefill: dict = {}
        for k, v in request.query_params.items():
            f = model_cls._fields.get(k)
            if f is None:
                continue
            if isinstance(f, Many2one):
                try:
                    prefill[k] = int(v)
                except (TypeError, ValueError):
                    continue
            else:
                prefill[k] = v
        # Body-only fragments are returned to HTMX-initiated GETs so
        # the floating dialog can drop the form straight into its
        # body without the layout chrome (sidebar, header, etc.).
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(
                view,
                None,
                env,
                mode="new",
                body_only=body_only,
                in_dialog=_form_in_dialog(request),
                current_path=str(request.url.path),
                prefill=prefill or None,
                **_form_list_nav(request),
            )
        )

    @app.get(
        "/web/views/{module}/{name}/record/{record_id}", response_class=HTMLResponse
    )
    def web_form_display(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        # HX-Request header set by HTMX -> return body fragment for
        # in-place swap; otherwise full page for direct navigation.
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(
                view,
                rec,
                env,
                mode="display",
                body_only=body_only,
                in_dialog=_form_in_dialog(request),
                current_path=str(request.url.path),
                **_form_list_nav(request),
            )
        )

    @app.get(
        "/web/views/{module}/{name}/record/{record_id}/edit",
        response_class=HTMLResponse,
    )
    def web_form_edit(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        if not env.has_access(view.model, "write"):
            raise PermissionError(f"You cannot edit {view.model} records.")
        rec = _load_record(env, view, record_id)
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(
                view,
                rec,
                env,
                mode="edit",
                body_only=body_only,
                in_dialog=_form_in_dialog(request),
                current_path=str(request.url.path),
                **_form_list_nav(request),
            )
        )

    @app.post(
        "/web/views/{module}/{name}/record/{record_id}", response_class=HTMLResponse
    )
    async def web_form_save(
        module: str,
        name: str,
        record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import (
            apply_o2m_commands,
            harvest_o2m_commands,
            parse_form_vals,
            render_form_page,
        )

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form, env)
        o2m_cmds, o2m_errors = harvest_o2m_commands(cls, form, env)
        body_only = request.headers.get("HX-Request") == "true"
        in_dialog = _form_in_dialog(request)
        if errors or o2m_errors:
            errors = {**errors, **o2m_errors}
            # Parse-side validation failed. Re-render the edit form with
            # per-field messages stamped + the user's typed values
            # resurrected so they don't have to retype.
            return HTMLResponse(
                render_form_page(
                    view,
                    rec,
                    env,
                    mode="edit",
                    body_only=body_only,
                    in_dialog=in_dialog,
                    errors=errors,
                    submitted=vals,
                    form_playback=form,
                    current_path=str(request.url.path),
                    **_form_list_nav(request),
                ),
                status_code=422,
            )
        try:
            with env.transaction():
                rec.write(vals)
                apply_o2m_commands(rec, o2m_cmds)
        except Exception as exc:  # noqa: BLE001
            # ORM-level failure (constraint, downstream DB error).
            # Show a top-level banner so the user sees why the save
            # didn't stick instead of getting a silent 500.
            return HTMLResponse(
                render_form_page(
                    view,
                    rec,
                    env,
                    mode="edit",
                    body_only=body_only,
                    in_dialog=in_dialog,
                    submitted=vals,
                    form_playback=form,
                    form_error=str(exc),
                    current_path=str(request.url.path),
                    **_form_list_nav(request),
                ),
                status_code=422,
            )
        env.cache.invalidate(model_name=view.model, ids=[record_id])
        if o2m_cmds:
            for oname, cmds in o2m_cmds.items():
                ofield = cls._fields.get(oname)
                if ofield is not None:
                    env.cache.invalidate(model_name=ofield.comodel_name)
        # When the form is being saved inside the floating dialog (the
        # client tags the request with X-PV-Dialog: 1), we don't want
        # to swap the dialog body with the display-mode form — the
        # dialog is about to close. Returning 204 + HX-Trigger tells
        # HTMX to skip the swap and fires the JS event the dialog
        # listens to in order to close and hand the result back to
        # its caller.
        if request.headers.get("X-PV-Dialog") == "1":
            payload = {
                "id": rec.id,
                "label": _display_value(rec),
                "model": view.model,
            }
            return Response(
                status_code=204,
                headers={
                    "HX-Trigger": json.dumps({
                        "pv-dialog-saved": payload,
                        "pv-toast": _form_save_toast_payload(rec),
                    }),
                },
            )
        return HTMLResponse(
            render_form_page(
                view,
                rec,
                env,
                mode="display",
                body_only=body_only,
                current_path=str(request.url.path),
                **_form_list_nav(request),
            ),
            headers=_form_save_toast_headers(rec),
        )

    @app.post("/web/views/{module}/{name}", response_class=HTMLResponse)
    async def web_form_create(
        module: str,
        name: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import (
            apply_o2m_commands,
            harvest_o2m_commands,
            parse_form_vals,
            render_form_page,
        )

        view = _require_form_view(_load_view(env, module, name))
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form, env)
        o2m_cmds, o2m_errors = harvest_o2m_commands(cls, form, env)
        body_only = request.headers.get("HX-Request") == "true"
        in_dialog = _form_in_dialog(request)
        if errors or o2m_errors:
            errors = {**errors, **o2m_errors}
            return HTMLResponse(
                render_form_page(
                    view,
                    None,
                    env,
                    mode="new",
                    body_only=body_only,
                    in_dialog=in_dialog,
                    errors=errors,
                    submitted=vals,
                    form_playback=form,
                    current_path=str(request.url.path),
                    **_form_list_nav(request),
                ),
                status_code=422,
            )
        try:
            with env.transaction():
                rec = env[view.model].create(vals)
                apply_o2m_commands(rec, o2m_cmds)
        except Exception as exc:  # noqa: BLE001
            return HTMLResponse(
                render_form_page(
                    view,
                    None,
                    env,
                    mode="new",
                    body_only=body_only,
                    in_dialog=in_dialog,
                    submitted=vals,
                    form_playback=form,
                    form_error=str(exc),
                    current_path=str(request.url.path),
                    **_form_list_nav(request),
                ),
                status_code=422,
            )
        if o2m_cmds:
            for oname, cmds in o2m_cmds.items():
                ofield = cls._fields.get(oname)
                if ofield is not None:
                    env.cache.invalidate(model_name=ofield.comodel_name)
        # See the matching block in ``web_form_save``: dialog-launched
        # creates respond with a 204 + HX-Trigger so the floating
        # dialog closes and hands ``{id, label, model}`` back to the
        # opener (the m2o combobox's "Create and edit", an o2m table's
        # "Add" button, etc.).
        if request.headers.get("X-PV-Dialog") == "1":
            payload = {
                "id": rec.id,
                "label": _display_value(rec),
                "model": view.model,
            }
            return Response(
                status_code=204,
                headers={
                    "HX-Trigger": json.dumps({
                        "pv-dialog-saved": payload,
                        "pv-toast": _form_save_toast_payload(rec, created=True),
                    }),
                },
            )
        return HTMLResponse(
            render_form_page(
                view,
                rec,
                env,
                mode="display",
                body_only=body_only,
                current_path=str(request.url.path),
                **_form_list_nav(request),
            ),
            headers=_form_save_toast_headers(rec, created=True),
        )

    # ---- graph / pivot interactive data endpoints ----
    #
    # Both return plain JSON so the Alpine toolbar components can
    # re-fetch on every control change without a full-page reload.
    # Auth mirrors /api/records — authenticated session required.

    @app.get("/api/graph/data")
    def api_graph_data(
        model: str = Query(...),
        groupby: str = Query(...),
        measure: str = Query(default="__count"),
        chart: str = Query(default="bar"),
        search: str = Query(default=""),
        filters: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        """Return aggregated JSON for one groupby + one measure."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if model not in registry:
            raise HTTPException(status_code=400, detail=f"Unknown model {model!r}")
        from .render import _build_search_domain, _format_group_label, _parse_filters

        model_cls = registry[model]
        Model = env[model]
        pseudo_spec = [{"name": n} for n, f in model_cls._fields.items() if f.is_stored]
        domain: list = []
        if search:
            domain.extend(_build_search_domain(model_cls, pseudo_spec, search))
        if filters:
            domain.extend(_parse_filters(model_cls, pseudo_spec, filters))

        rows = Model.read_group(domain, groupby=[groupby], measures=[measure])

        gfname, gtrunc = (groupby.split(":", 1) if ":" in groupby else (groupby, None))
        label_key = f"{groupby}__label"
        labels: list[str] = []
        values: list[float] = []
        for r in rows:
            raw = r.get(groupby)
            lbl = (str(r[label_key]) if (label_key in r and r[label_key] is not None)
                   else _format_group_label(raw, gfname, gtrunc, model_cls))
            labels.append(lbl)
            try:
                values.append(float(r.get(measure, 0) or 0))
            except (TypeError, ValueError):
                values.append(0.0)

        if measure == "__count":
            measure_label = "Count"
        else:
            mfname = measure.split(":", 1)[0]
            mf = model_cls._fields.get(mfname)
            base = (mf.string or mfname) if mf else mfname
            agg = measure.split(":", 1)[1] if ":" in measure else "sum"
            measure_label = f"{base} ({agg})"

        return {
            "labels": labels,
            "values": values,
            "measure_label": measure_label,
            "chart_type": chart,
            "groupby": groupby,
            "measure": measure,
        }

    @app.get("/api/pivot/data")
    def api_pivot_data(
        model: str = Query(...),
        row_groupby: str = Query(default=""),
        col_groupby: str = Query(default=""),
        measures: str = Query(default="__count"),
        search: str = Query(default=""),
        filters: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        """Return cross-tabulated JSON for row_groupby × col_groupby × measures."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if model not in registry:
            raise HTTPException(status_code=400, detail=f"Unknown model {model!r}")
        from .render import (
            _build_search_domain,
            _format_pivot_cell,
            _measure_label as _ml,
            _parse_filters,
            _pivot_axis_labels,
        )
        from itertools import product as _ip

        model_cls = registry[model]
        Model = env[model]
        pseudo_spec = [{"name": n} for n, f in model_cls._fields.items() if f.is_stored]
        domain: list = []
        if search:
            domain.extend(_build_search_domain(model_cls, pseudo_spec, search))
        if filters:
            domain.extend(_parse_filters(model_cls, pseudo_spec, filters))

        row_specs = [s for s in row_groupby.split(",") if s] if row_groupby else []
        col_specs = [s for s in col_groupby.split(",") if s] if col_groupby else []
        meas_list = [s for s in measures.split(",") if s] if measures else ["__count"]

        flat = Model.read_group(domain, groupby=row_specs + col_specs, measures=meas_list)

        row_axes = _pivot_axis_labels(flat, row_specs, model_cls)
        col_axes = _pivot_axis_labels(flat, col_specs, model_cls)

        cell_index: dict = {}
        for r in flat:
            rk = tuple(r.get(s) for s in row_specs)
            ck = tuple(r.get(s) for s in col_specs)
            cell_index[(rk, ck)] = {m: r.get(m) for m in meas_list}

        row_combos = (list(_ip(*[[e["value"] for e in a] for a in row_axes]))
                      if row_axes else [()])
        col_combos = (list(_ip(*[[e["value"] for e in a] for a in col_axes]))
                      if col_axes else [()])

        # Header levels for col groupbys
        header_levels: list[list[dict]] = []
        for li, level in enumerate(col_axes):
            below = col_axes[li + 1:]
            span_per = max(1, len(level))
            for b in below:
                span_per *= max(1, len(b))
            header_levels.append([
                {"label": e["label"], "colspan": span_per * len(meas_list)}
                for e in level
            ])

        measure_label_row = [
            {"label": _ml(m, model_cls), "colspan": 1}
            for _ in col_combos for m in meas_list
        ]

        body_rows: list[dict] = []
        for rc in row_combos:
            row_labels: list[str] = []
            for li2, kv in enumerate(rc):
                row_labels.append(
                    next((e["label"] for e in row_axes[li2] if e["value"] == kv),
                         str(kv))
                )
            cells: list[dict] = []
            rt: dict = {m: 0 for m in meas_list}
            for cc in col_combos:
                mac = cell_index.get((rc, cc))
                for m in meas_list:
                    v = mac.get(m) if mac else None
                    cells.append({"display": _format_pivot_cell(v, m), "is_total": False})
                    if v is not None:
                        try:
                            rt[m] += float(v)
                        except (TypeError, ValueError):
                            pass
            for m in meas_list:
                cells.append({"display": _format_pivot_cell(rt[m], m), "is_total": True})
            body_rows.append({"labels": row_labels, "cells": cells})

        col_totals: list[dict] = []
        gg: dict = {m: 0 for m in meas_list}
        for cc in col_combos:
            for m in meas_list:
                run = 0.0
                for rc in row_combos:
                    mac = cell_index.get((rc, cc))
                    if mac is None:
                        continue
                    v = mac.get(m)
                    if v is None:
                        continue
                    try:
                        run += float(v)
                    except (TypeError, ValueError):
                        pass
                col_totals.append({"display": _format_pivot_cell(run, m), "is_total": True})
                gg[m] += run
        for m in meas_list:
            col_totals.append({"display": _format_pivot_cell(gg[m], m), "is_total": True})

        row_axis_titles: list[str] = []
        for spec in row_specs:
            fname = spec.split(":", 1)[0]
            f = model_cls._fields.get(fname)
            t = (f.string or fname) if f else fname
            if ":" in spec:
                t += f" ({spec.split(':',1)[1]})"
            row_axis_titles.append(t)

        return {
            "header_levels": header_levels,
            "measure_label_row": measure_label_row,
            "grand_header": {"label": "Total", "colspan": len(meas_list)},
            "body_rows": body_rows,
            "col_totals": col_totals,
            "row_axis_titles": row_axis_titles,
            "measure_count": len(meas_list),
            "col_combos_count": len(col_combos),
            "row_specs": row_specs,
            "col_specs": col_specs,
            "measures": meas_list,
        }

    @app.get("/api/view-fields")
    def api_view_fields(
        model: str = Query(...),
        env: Environment = Depends(get_env),
    ):
        """Return field metadata used by graph/pivot toolbars to populate
        their groupby / measure dropdowns."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if model not in registry:
            raise HTTPException(status_code=400, detail=f"Unknown model {model!r}")
        from .fields import Boolean, Date, Datetime, Float, Integer, Many2one

        model_cls = registry[model]
        groupable: list[dict] = []
        measurable: list[dict] = []

        # Count is always available as a measure.
        measurable.append({"value": "__count", "label": "Count"})

        for fname, field in model_cls._fields.items():
            if not field.is_stored or field.private:
                continue
            label = field.string or fname
            ft = type(field).__name__

            # Groupable: Char, Integer, Boolean, Many2one, Date, Datetime
            if isinstance(field, (Many2one, Date, Datetime)):
                groupable.append({"value": fname, "label": label, "type": ft})
                if isinstance(field, (Date, Datetime)):
                    for trunc in ("day", "week", "month", "quarter", "year"):
                        groupable.append({
                            "value": f"{fname}:{trunc}",
                            "label": f"{label} ({trunc})",
                            "type": ft,
                        })
            elif not isinstance(field, (Float, Boolean)):
                # Char, Integer and others are groupable as-is
                groupable.append({"value": fname, "label": label, "type": ft})

            # Measurable: numeric fields only
            if isinstance(field, (Integer, Float)):
                measurable.append({
                    "value": f"{fname}:sum",
                    "label": f"{label} (sum)",
                    "type": ft,
                })
                measurable.append({
                    "value": f"{fname}:avg",
                    "label": f"{label} (avg)",
                    "type": ft,
                })

        return {"groupable": groupable, "measurable": measurable}

    # ---- Report builder (secure compile + export) ----

    def _report_or_404(env: Environment, report_id: int):
        from .reports.service import can_run_report, load_report

        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if "ir.report" not in registry:
            raise HTTPException(status_code=404, detail="Reports module not installed")
        rec = load_report(env, report_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Report not found")
        try:
            if not can_run_report(env, rec):
                raise HTTPException(status_code=403, detail="Not allowed to run this report")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return rec

    @app.get("/api/reports/{report_id}/preview")
    def api_report_preview(
        report_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .reports.schema import ReportDefinitionError
        from .reports.service import (
            PREVIEW_LIMIT,
            definition_dict,
            execute_report,
            log_run,
            parse_run_params,
            result_to_json,
        )

        rec = _report_or_404(env, report_id)
        defn = definition_dict(rec)
        params = parse_run_params(defn, dict(request.query_params))
        try:
            result = execute_report(env, rec, params, limit=PREVIEW_LIMIT)
        except ReportDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        log_run(
            env, rec,
            row_count=result.row_count,
            duration_ms=result.duration_ms,
            fmt="preview",
        )
        return result_to_json(result)

    @app.get("/api/reports/{report_id}/export.xlsx")
    def api_report_export_xlsx(
        report_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .reports.export_xlsx import export_xlsx
        from .reports.schema import ReportDefinitionError
        from .reports.service import (
            definition_dict,
            execute_report,
            log_run,
            parse_run_params,
        )

        rec = _report_or_404(env, report_id)
        defn = definition_dict(rec)
        params = parse_run_params(defn, dict(request.query_params))
        try:
            result = execute_report(env, rec, params)
            data = export_xlsx(result, title=rec.name)
        except ReportDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        log_run(
            env, rec,
            row_count=result.row_count,
            duration_ms=result.duration_ms,
            fmt="xlsx",
        )
        safe_name = (rec.name or "report").replace('"', "")[:80]
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
        )

    @app.get("/api/reports/{report_id}/export.csv")
    def api_report_export_csv(
        report_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .reports.export_xlsx import export_csv
        from .reports.schema import ReportDefinitionError
        from .reports.service import (
            definition_dict,
            execute_report,
            log_run,
            parse_run_params,
        )

        rec = _report_or_404(env, report_id)
        defn = definition_dict(rec)
        params = parse_run_params(defn, dict(request.query_params))
        try:
            result = execute_report(env, rec, params)
            body = export_csv(result)
        except ReportDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        log_run(
            env, rec,
            row_count=result.row_count,
            duration_ms=result.duration_ms,
            fmt="csv",
        )
        safe_name = (rec.name or "report").replace('"', "")[:80]
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )

    @app.get("/web/reports/{report_id}/run", response_class=HTMLResponse)
    def web_report_run(
        report_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import render_report_run_page

        if env.uid is None:
            return _login_redirect(request)
        rec = _report_or_404(env, report_id)
        return HTMLResponse(
            render_report_run_page(
                rec, env, current_path=str(request.url.path),
            )
        )

    def _require_report_editor(env: Environment) -> None:
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if "ir.report" not in registry:
            raise HTTPException(status_code=404, detail="Reports module not installed")
        try:
            env.check_access("ir.report", "write")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    @app.get("/api/reports/models")
    def api_reports_models(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_readable_models
        return {"models": list_readable_models(env)}

    @app.get("/api/mail/templates/models")
    def api_mail_template_models(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_readable_models
        return {"models": list_readable_models(env)}

    @app.get("/api/mail/templates/variables")
    def api_mail_template_variables(
        model: str = Query(""),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .mail_template_fields import list_template_variables
        try:
            return list_template_variables(env, model)
        except (ValueError, PermissionError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/mail/templates/preview")
    def api_mail_template_preview(
        body: dict = Body(...),
        env: Environment = Depends(get_env),
    ):
        """Render the **current draft** of a template against a record.

        Body: ``{model, subject, body_html, res_id?, extra?}``.

        We render the draft (not a stored ``mail.template`` row) so the
        admin can preview unsaved edits live. ``res_id`` is optional —
        when omitted, the renderer falls back to the first record of
        ``model`` (or an empty recordset if none exist), so a brand-new
        template still shows *something*.
        """
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            env.check_access("mail.template", "read")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

        model = str(body.get("model") or "").strip()
        if not model:
            raise HTTPException(status_code=400, detail="`model` is required")
        if model not in registry:
            raise HTTPException(status_code=400, detail=f"Unknown model {model!r}")

        from .mail_template_render import (
            build_mail_template_context,
            render_mail_template_string,
        )

        subject_src = str(body.get("subject") or "")
        body_src = str(body.get("body_html") or "")
        extra = body.get("extra") if isinstance(body.get("extra"), dict) else None

        Model = env[model]
        record = Model
        res_id_raw = body.get("res_id")
        if res_id_raw not in ("", None):
            try:
                res_id = int(res_id_raw)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="`res_id` must be an integer"
                ) from None
            rec = Model.browse(res_id)
            if not rec._ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"No {model} record with id={res_id}",
                )
            record = rec
        else:
            sample = Model.search([], limit=1)
            if sample._ids:
                record = sample

        try:
            context = build_mail_template_context(
                env, model=model, record=record, extra=extra
            )
            subject = render_mail_template_string(subject_src, context)
            body_html = render_mail_template_string(body_src, context)
        except ValueError as e:
            # Render errors land here — surface as 422 so the editor can
            # show them inline without confusing the user with a generic 500.
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {
            "subject": subject,
            "body_html": body_html,
            "res_id": record.id if getattr(record, "_ids", ()) else None,
        }

    @app.get("/api/reports/fields")
    def api_reports_fields(model: str = Query(...), env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_exportable_fields
        try:
            return list_exportable_fields(env, model)
        except (ValueError, PermissionError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/reports/field-level")
    def api_reports_field_level(
        root: str = Query(...),
        prefix: str = Query(""),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_fields_level
        try:
            return list_fields_level(env, root, prefix=prefix)
        except (ValueError, PermissionError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/api/reports/currencies")
    def api_reports_currencies(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_active_currencies
        return {"currencies": list_active_currencies(env)}

    @app.post("/api/reports/validate-run")
    async def api_reports_validate_run(
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.schema import ReportDefinitionError
        from .reports.execute import run_report
        from .reports.service import PREVIEW_LIMIT, result_to_json
        from .reports.compile import parse_definition

        body = await request.json()
        defn = parse_definition(body)
        try:
            result = run_report(env, defn, {}, limit=PREVIEW_LIMIT)
            return result_to_json(result)
        except ReportDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    @app.post("/api/reports")
    async def api_reports_create(request: Request, env: Environment = Depends(get_env)):
        import json as _json
        _require_report_editor(env)
        body = await request.json()
        Report = env["ir.report"]
        defn = body.get("definition") or {}
        rec = Report.create({
            "name": body.get("name", "Untitled report"),
            "description": body.get("description") or False,
            "root_model": body.get("root_model") or defn.get("root"),
            "definition": _json.dumps(defn, indent=2),
            "row_limit": int(body.get("row_limit") or 10000),
            "output_format": body.get("output_format") or "xlsx",
            "schedule_active": bool(body.get("schedule_active")),
            "active": True,
        })
        return {"id": rec.id}

    @app.put("/api/reports/{report_id}")
    async def api_reports_update(
        report_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        import json as _json
        _require_report_editor(env)
        Report = env["ir.report"]
        recs = Report.search([("id", "=", report_id)], limit=1)
        if not recs:
            raise HTTPException(status_code=404, detail="Report not found")
        recs.ensure_one()
        body = await request.json()
        defn = body.get("definition")
        vals = {
            "name": body.get("name", recs.name),
            "description": body.get("description", recs.description),
            "root_model": body.get("root_model", recs.root_model),
            "row_limit": int(body.get("row_limit", recs.row_limit or 10000)),
            "output_format": body.get("output_format", recs.output_format or "xlsx"),
            "schedule_active": bool(body.get("schedule_active", recs.schedule_active)),
        }
        if defn is not None:
            vals["definition"] = _json.dumps(defn, indent=2)
        recs.write(vals)
        return {"id": recs.id}

    @app.get("/api/reports/{report_id}/export.pdf")
    def api_report_export_pdf(
        report_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .reports.export_pdf import export_pdf
        from .reports.schema import ReportDefinitionError
        from .reports.service import (
            definition_dict, execute_report, log_run, parse_run_params,
        )
        rec = _report_or_404(env, report_id)
        defn = definition_dict(rec)
        params = parse_run_params(defn, dict(request.query_params))
        try:
            result = execute_report(env, rec, params)
            data = export_pdf(result, title=rec.name)
        except ReportDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        log_run(env, rec, row_count=result.row_count, duration_ms=result.duration_ms, fmt="pdf")
        safe_name = (rec.name or "report").replace('"', "")[:80]
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
        )

    @app.post("/api/reports/{report_id}/schedule")
    async def api_report_schedule(
        report_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        _require_report_editor(env)
        from .reports.scheduler import disable_schedule, ensure_daily_cron
        Report = env["ir.report"]
        recs = Report.search([("id", "=", report_id)], limit=1)
        if not recs:
            raise HTTPException(status_code=404, detail="Report not found")
        recs.ensure_one()
        body = await request.json()
        recs.write({
            "output_format": body.get("output_format", recs.output_format or "xlsx"),
            "schedule_active": bool(body.get("active", body.get("schedule_active"))),
        })
        if recs.schedule_active:
            ensure_daily_cron(env, recs)
        else:
            disable_schedule(env, recs)
        return {"ok": True, "cron_id": recs.cron_id.id if recs.cron_id else None}

    @app.get("/web/reports/build", response_class=HTMLResponse)
    def web_report_build(request: Request, env: Environment = Depends(get_env)):
        from .render import render_report_builder_page
        if env.uid is None:
            return _login_redirect(request)
        # Let PermissionError reach the global handler so the browser
        # gets the styled access-denied page, not a JSON error.
        env.check_access("ir.report", "create")
        return HTMLResponse(render_report_builder_page(env, report_rec=None, current_path=str(request.url.path)))

    @app.get("/web/reports/{report_id}/build", response_class=HTMLResponse)
    def web_report_build_edit(
        report_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        from .render import render_report_builder_page
        if env.uid is None:
            return _login_redirect(request)
        Report = env["ir.report"]
        recs = Report.search([("id", "=", report_id)], limit=1)
        if not recs:
            raise HTTPException(status_code=404, detail="Report not found")
        env.check_access("ir.report", "write")
        return HTMLResponse(
            render_report_builder_page(env, report_rec=recs, current_path=str(request.url.path))
        )

    @app.get("/web/chatter/panel", response_class=HTMLResponse)
    def web_chatter_panel(
        request: Request,
        model: str = Query(...),
        res_id: int = Query(...),
        filter: str = Query("all", alias="filter"),
        mode: str = Query("note"),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_chatter_panel

        return HTMLResponse(
            render_chatter_panel(
                env,
                model.strip(),
                res_id,
                filter_key=filter,
                composer_mode=mode,
            )
        )

    @app.post("/web/chatter/post", response_class=HTMLResponse)
    async def web_chatter_post(
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .mail_chatter import _normalize_filter, _parse_attachment_ids, post_chatter_message
        from .render import render_chatter_panel

        form = await request.form()
        model = (form.get("model") or "").strip()
        body = (form.get("body") or "").strip()
        action = (form.get("action") or "note").strip().lower()
        filter_key = _normalize_filter(form.get("filter"))
        composer_mode = "email" if action == "email" else "note"
        recipient = (form.get("recipient_email") or "").strip()
        subject = (form.get("subject") or "").strip()
        att_raw = form.getlist("attachment_ids") if hasattr(form, "getlist") else []
        if not att_raw and form.get("attachment_ids"):
            att_raw = [form.get("attachment_ids")]
        attachment_ids = _parse_attachment_ids(att_raw)
        try:
            res_id = int(form.get("res_id"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid record id") from exc
        if not model:
            raise HTTPException(status_code=400, detail="model is required")
        try:
            with env.transaction():
                post_chatter_message(
                    env,
                    model,
                    res_id,
                    body,
                    action=action,
                    recipient_email=recipient,
                    subject=subject,
                    attachment_ids=attachment_ids,
                )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            return HTMLResponse(
                render_chatter_panel(
                    env,
                    model,
                    res_id,
                    filter_key=filter_key,
                    composer_mode=composer_mode,
                    error=str(exc),
                ),
                status_code=422,
            )
        return HTMLResponse(
            render_chatter_panel(
                env,
                model,
                res_id,
                filter_key=filter_key,
                composer_mode=composer_mode,
            )
        )

    # ---- workflow designer & runtime API ----

    def _require_workflow_editor(env: Environment) -> None:
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if "workflow.definition" not in registry:
            raise HTTPException(status_code=404, detail="Workflow module not installed")
        try:
            env.check_access("workflow.definition", "write")
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    @app.get("/web/workflow/inbox", response_class=HTMLResponse)
    def web_workflow_inbox(request: Request, env: Environment = Depends(get_env)):
        from .render import render_workflow_inbox_page

        if env.uid is None:
            return _login_redirect(request)
        return HTMLResponse(
            render_workflow_inbox_page(env, current_path=str(request.url.path))
        )

    @app.get(
        "/web/workflow/instances/{instance_id}/transition/{transition_key}",
        response_class=HTMLResponse,
    )
    def web_workflow_transition_form(
        instance_id: int,
        transition_key: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import render_workflow_transition_form

        if env.uid is None:
            return _auth_required_response(request)
        html = render_workflow_transition_form(env, instance_id, transition_key)
        if html is None:
            raise HTTPException(status_code=404, detail="Transition not available")
        return HTMLResponse(html)

    @app.post(
        "/web/workflow/instances/{instance_id}/transition/{transition_key}",
        response_class=HTMLResponse,
    )
    async def web_workflow_transition_submit(
        instance_id: int,
        transition_key: str,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import render_workflow_transition_form
        from .workflow.engine import WorkflowEngine
        from .workflow.schema import WorkflowDefinitionError

        if env.uid is None:
            return _auth_required_response(request)
        if "workflow.instance" not in env.registry:
            raise HTTPException(status_code=404, detail="Workflow not installed")
        Instance = env["workflow.instance"]
        inst = Instance.search([("id", "=", instance_id)], limit=1)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        inst.ensure_one()
        form = await request.form()
        values = {
            k: v for k, v in form.items()
            if k not in ("_csrf",) and not str(k).startswith("_")
        }
        try:
            with env.transaction():
                WorkflowEngine.apply_transition(env, inst, transition_key, values)
        except WorkflowDefinitionError as exc:
            return HTMLResponse(
                render_workflow_transition_form(
                    env,
                    instance_id,
                    transition_key,
                    form_error=str(exc),
                    values=values,
                )
                or "",
                status_code=422,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if request.headers.get("X-PV-Dialog") == "1":
            return Response(
                status_code=204,
                headers={
                    "HX-Trigger": json.dumps({"pv-dialog-saved": {"ok": True}}),
                },
            )
        from .home import home_url

        return RedirectResponse(
            request.headers.get("Referer") or home_url(), status_code=303
        )

    @app.get("/web/workflow/build", response_class=HTMLResponse)
    def web_workflow_build(request: Request, env: Environment = Depends(get_env)):
        from .render import render_workflow_builder_page

        if env.uid is None:
            return _login_redirect(request)
        env.check_access("workflow.definition", "create")
        return HTMLResponse(
            render_workflow_builder_page(env, workflow_rec=None, current_path=str(request.url.path))
        )

    @app.get("/web/workflow/{workflow_id}/build", response_class=HTMLResponse)
    def web_workflow_build_edit(
        workflow_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        from .render import render_workflow_builder_page

        if env.uid is None:
            return _login_redirect(request)
        Definition = env["workflow.definition"]
        recs = Definition.search([("id", "=", workflow_id)], limit=1)
        if not recs:
            raise HTTPException(status_code=404, detail="Workflow not found")
        env.check_access("workflow.definition", "write")
        return HTMLResponse(
            render_workflow_builder_page(env, workflow_rec=recs, current_path=str(request.url.path))
        )

    @app.get("/api/workflow/models")
    def api_workflow_models(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .reports.fields_api import list_readable_models

        return list_readable_models(env)

    @app.get("/api/workflow/fields")
    def api_workflow_fields(model: str, env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .workflow.service import list_model_fields

        return list_model_fields(env, model)

    @app.get("/api/workflow/groups")
    def api_workflow_groups(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .workflow.service import list_groups

        return list_groups(env)

    @app.get("/api/workflow/users")
    def api_workflow_users(env: Environment = Depends(get_env)):
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .workflow.service import list_users

        return list_users(env)

    @app.post("/api/workflow")
    async def api_workflow_create(request: Request, env: Environment = Depends(get_env)):
        import json as _json

        from .workflow.schema import WorkflowDefinitionError, validate_definition

        _require_workflow_editor(env)
        body = await request.json()
        defn = body.get("definition") or {}
        validate_definition(defn, registry)
        Definition = env["workflow.definition"]
        rec = Definition.create({
            "name": body.get("name", "Untitled workflow"),
            "description": body.get("description") or False,
            "model": body.get("model") or defn.get("model"),
            "definition": _json.dumps(defn, indent=2),
            "active": bool(body.get("active", True)),
        })
        return {"id": rec.id}

    @app.put("/api/workflow/{workflow_id}")
    async def api_workflow_update(
        workflow_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        from .workflow.schema import WorkflowDefinitionError
        from .workflow.service import save_definition

        _require_workflow_editor(env)
        Definition = env["workflow.definition"]
        recs = Definition.search([("id", "=", workflow_id)], limit=1)
        if not recs:
            raise HTTPException(status_code=404, detail="Workflow not found")
        recs.ensure_one()
        body = await request.json()
        defn = body.get("definition")
        if defn is None:
            raise HTTPException(status_code=400, detail="definition required")
        try:
            save_definition(
                env,
                recs,
                {
                    "name": body.get("name", recs.name),
                    "description": body.get("description", recs.description),
                    "model": body.get("model", recs.model),
                    "active": body.get("active", recs.active),
                },
                defn,
            )
        except WorkflowDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"id": recs.id}

    @app.post("/api/workflow/instances/start")
    async def api_workflow_start(request: Request, env: Environment = Depends(get_env)):
        from .workflow.engine import WorkflowDefinitionError, WorkflowEngine

        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        body = await request.json()
        model = body.get("model")
        res_id = int(body.get("res_id") or 0)
        if not model or not res_id:
            raise HTTPException(status_code=400, detail="model and res_id required")
        try:
            env.check_access(model, "read")
            record = env[model].browse(res_id)
            WorkflowEngine.start(env, record)
        except WorkflowDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return {"ok": True}

    @app.post("/api/workflow/instances/{instance_id}/transition")
    async def api_workflow_transition(
        instance_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        from .workflow.engine import WorkflowEngine
        from .workflow.schema import WorkflowDefinitionError

        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        Instance = env["workflow.instance"]
        inst = Instance.search([("id", "=", instance_id)], limit=1)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        inst.ensure_one()
        body = await request.json()
        try:
            WorkflowEngine.apply_transition(
                env,
                inst,
                body.get("transition", ""),
                body.get("values") or {},
            )
        except WorkflowDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return {"ok": True, "state": inst.state}

    @app.post("/api/workflow/approvals/{approval_id}/act")
    async def api_workflow_approval_act(
        approval_id: int, request: Request, env: Environment = Depends(get_env),
    ):
        from .workflow.engine import WorkflowDefinitionError, WorkflowEngine

        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        Approval = env["workflow.approval"]
        appr = Approval.search([("id", "=", approval_id)], limit=1)
        if not appr:
            raise HTTPException(status_code=404, detail="Approval not found")
        appr.ensure_one()
        body = await request.json()
        try:
            WorkflowEngine.approve(
                env,
                appr,
                approved=bool(body.get("approved", True)),
                comment=body.get("comment") or "",
            )
        except WorkflowDefinitionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        return {"ok": True}

    # ---- site root + home dashboard ----

    @app.get("/", response_class=HTMLResponse)
    def site_root(request: Request, env: Environment = Depends(get_env)):
        from .home import home_url, landing_enabled, login_url
        from .render import render_home_page, render_landing_page

        if env.uid is not None:
            target = home_url()
            if target == "/":
                return HTMLResponse(
                    render_home_page(env, current_path="/")
                )
            return RedirectResponse(target, status_code=302)
        if landing_enabled():
            return HTMLResponse(
                render_landing_page(env, current_path=str(request.url.path))
            )
        return RedirectResponse(login_url(), status_code=302)

    @app.get("/web/admin", response_class=HTMLResponse)
    def web_admin(request: Request, env: Environment = Depends(get_env)):
        from .home import home_url, login_url
        from .render import render_admin_page, render_home_page

        if env.uid is None:
            return RedirectResponse(login_url(), status_code=302)
        target = home_url()
        if target not in ("/web/admin", "/web/admin/"):
            if target == "/":
                return HTMLResponse(
                    render_home_page(env, current_path="/")
                )
            return RedirectResponse(target, status_code=302)
        return HTMLResponse(
            render_admin_page(env=env, current_path=str(request.url.path))
        )

    # ---- Apps catalog (read-only in Slice 1; install/upgrade in Slice 2) ----

    @app.get("/web/apps", response_class=HTMLResponse)
    def web_apps(request: Request, env: Environment = Depends(get_env)):
        from .render import render_apps_page

        if env.uid is None:
            return _login_redirect(request)
        return HTMLResponse(
            render_apps_page(
                env=env,
                module_roots=app.state.module_roots,
                current_path=str(request.url.path),
            )
        )

    @app.get("/web/apps/{name}", response_class=HTMLResponse)
    def web_app_detail(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        from .render import render_apps_detail_page

        if env.uid is None:
            return _login_redirect(request)
        html = render_apps_detail_page(
            env=env,
            module_roots=app.state.module_roots,
            name=name,
            current_path=str(request.url.path),
        )
        if html is None:
            raise HTTPException(status_code=404, detail=f"Unknown module {name!r}")
        return HTMLResponse(html)

    def _require_admin(env: Environment) -> None:
        """Only the superuser (uid=1) may install or upgrade modules.

        Installing runs hooks, executes user-supplied install_hook code,
        and writes new tables — way past what normal ACL covers.
        """
        if env.uid != 1:
            raise HTTPException(
                status_code=403,
                detail="Module install / upgrade requires superuser (uid=1)",
            )

    def _header_safe_text(text: str) -> str:
        """HTTP response headers must be latin-1 (Starlette)."""
        for ch in ("\u2014", "\u2013", "\u2212", "\u2026"):
            text = text.replace(ch, "-")
        return text.encode("latin-1", "replace").decode("latin-1")

    def _apps_action_response(
        request: Request, env: Environment, result: dict
    ) -> Response:
        """Convert an install/upgrade result into an HTMX response.

        HTMX clients get an empty body with ``HX-Redirect`` to the main
        shell (Odoo-style full reload). The sync summary is appended as
        ``?pv_flash=`` on the redirect URL so the landing page can show it
        after load (custom headers / sessionStorage were unreliable with HTMX).
        """
        from urllib.parse import quote

        message = _header_safe_text(result.get("message", "Module updated."))
        from .home import home_url

        flash_base = home_url() if home_url() != "/" else "/web/admin"
        redirect = f"{flash_base}?pv_flash={quote(message, safe='')}"
        if request.headers.get("HX-Request") == "true":
            return Response(
                status_code=204,
                headers={"HX-Redirect": redirect},
            )
        return RedirectResponse(redirect, status_code=303)

    @app.post("/web/apps/{name}/install")
    def web_app_install(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import install_module_action

        try:
            result = install_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        installed = result.get("installed") or []
        if installed:
            from .loader import register_web_routes

            register_web_routes(
                app, app.state.module_roots, only=set(installed),
            )
        return _apps_action_response(request, env, result)

    @app.post("/web/apps/{name}/upgrade")
    def web_app_upgrade(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import upgrade_module_action

        try:
            result = upgrade_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

    @app.post("/web/apps/{name}/sync")
    def web_app_sync(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import sync_module_action

        try:
            result = sync_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

    @app.get("/web/apps/{name}/uninstall-preview")
    def web_app_uninstall_preview(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        """Dry-run for the uninstall flow — returns the JSON the confirm
        modal renders into a "this is what we'll do / why we won't"
        summary. Auth-gated like the action endpoints since exposing
        the cleanup map is itself a small information leak."""
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import uninstall_preview

        return uninstall_preview(env, app.state.module_roots, name)

    @app.post("/web/apps/{name}/uninstall")
    def web_app_uninstall(
        name: str, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import uninstall_module_action

        try:
            result = uninstall_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

    @app.post("/web/cron/{cron_id}/run-now")
    def web_cron_run_now(
        cron_id: int, request: Request, env: Environment = Depends(get_env)
    ):
        """Execute a single cron job on demand.

        Stamps ``lastcall`` and advances ``nextcall``. Admin-gated
        since cron actions can be arbitrary Python via
        ``ir.actions.server`` ``action_type="code"``.

        Returns the re-rendered ``cron.form`` body so the
        ``hx-target="#pyvelm-form-shell"`` swap immediately shows the
        new ``lastcall`` / ``nextcall`` values (localized to the
        active company's tz). Adds an ``HX-Trigger: pv-toast`` event
        so the layout's ``pvToast`` stack surfaces success / failure.
        """
        import json as _json

        from .render import render_form_page

        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        Cron = env["ir.cron"]
        if not Cron.search([("id", "=", cron_id)]):
            raise HTTPException(404, f"ir.cron({cron_id}) not found")
        job = Cron.browse(cron_id)
        try:
            job.run_now()
            message = f"Ran {job.name!r}"
        except Exception as exc:  # noqa: BLE001
            message = f"Failed: {exc}"
        view = _load_view(env, "admin", "cron.form")
        html = render_form_page(
            view, job, env, mode="display", body_only=True,
        )
        return HTMLResponse(
            html,
            headers={
                "HX-Trigger": _json.dumps({"pv-toast": message}),
            },
        )

    # ---------------------------------------------------------------
    # Email composer endpoints (mail_compose module)
    # ---------------------------------------------------------------

    def _compose_form_html(env, composer_id: int) -> str:
        from .render import render_form_page

        view = _load_view(env, "mail_compose", "mail_compose.form")
        rec = env["mail.compose.message"].browse(composer_id)
        if not rec._ids:
            raise HTTPException(404, f"mail.compose.message({composer_id}) not found")
        return render_form_page(view, rec, env, mode="edit", body_only=True)

    @app.get("/web/mail/compose/launch", response_class=HTMLResponse)
    def web_mail_compose_launch(
        request: Request,
        env: Environment = Depends(get_env),
        model: str = "",
        res_id: int = 0,
        template_id: int = 0,
        to: str = "",
    ):
        """Create a draft composer + return the form fragment.

        Opens inside PvDialog (set ``hx-target=#pv-fdialog-body``) or as
        a standalone page when navigated to directly.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "mail.compose.message" not in env.registry:
            raise HTTPException(404, "mail_compose module is not installed")
        Compose = env.registry["mail.compose.message"]
        composer = Compose.launch(
            env,
            model=model or None,
            res_id=res_id or None,
            template_id=template_id or None,
            recipient_to=to,
        )
        return HTMLResponse(_compose_form_html(env, composer.id))

    @app.post("/web/mail/compose/{composer_id}/apply-template", response_class=HTMLResponse)
    async def web_mail_compose_apply_template(
        composer_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Re-render the linked template into subject/body, then return the form."""
        import json as _json

        if env.uid is None:
            return _auth_required_response(request)
        if "mail.compose.message" not in env.registry:
            raise HTTPException(404, "mail_compose module is not installed")
        composer = env["mail.compose.message"].browse(composer_id)
        if not composer._ids:
            raise HTTPException(404, f"mail.compose.message({composer_id}) not found")
        # Persist any in-flight edits to template_id so the apply uses
        # the operator's current selection, not whatever's in the DB.
        form = await request.form()
        tpl_raw = (form.get("template_id") or "").strip()
        if tpl_raw:
            try:
                composer.write({"template_id": int(tpl_raw)})
            except (TypeError, ValueError):
                pass
        try:
            composer.action_apply_template()
            message = "Template applied" if composer.template_id else "No template selected"
        except Exception as exc:  # noqa: BLE001
            message = f"Apply failed: {exc}"
        return HTMLResponse(
            _compose_form_html(env, composer.id),
            headers={"HX-Trigger": _json.dumps({"pv-toast": message})},
        )

    @app.post("/web/mail/compose/{composer_id}/send", response_class=HTMLResponse)
    async def web_mail_compose_send(
        composer_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Queue the composer's content as outgoing mail."""
        import json as _json

        if env.uid is None:
            return _auth_required_response(request)
        if "mail.compose.message" not in env.registry:
            raise HTTPException(404, "mail_compose module is not installed")
        composer = env["mail.compose.message"].browse(composer_id)
        if not composer._ids:
            raise HTTPException(404, f"mail.compose.message({composer_id}) not found")
        # Pick up any unsaved form edits before sending — the user
        # likely changed To/Subject/body after creating the draft.
        form = await request.form()
        updates: dict = {}
        for key in (
            "recipient_to",
            "recipient_cc",
            "recipient_bcc",
            "reply_to",
            "subject",
            "body_html",
        ):
            val = form.get(key)
            if val is not None:
                updates[key] = val
        tpl_raw = (form.get("template_id") or "").strip()
        if tpl_raw:
            try:
                updates["template_id"] = int(tpl_raw)
            except (TypeError, ValueError):
                pass
        if updates:
            composer.write(updates)
        try:
            composer.action_send()
            message = "Email queued for delivery"
        except Exception as exc:  # noqa: BLE001
            message = f"Send failed: {exc}"
        return HTMLResponse(
            _compose_form_html(env, composer.id),
            headers={"HX-Trigger": _json.dumps({"pv-toast": message})},
        )

    @app.post("/web/mail/compose/{composer_id}/save-as-template", response_class=HTMLResponse)
    async def web_mail_compose_save_as_template(
        composer_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Clone the composer's content into a new ``mail.template``.

        The template's name defaults to the composer subject — operators
        rename it after creation if needed. Requires a bound ``model``.
        """
        import json as _json

        if env.uid is None:
            return _auth_required_response(request)
        if "mail.compose.message" not in env.registry:
            raise HTTPException(404, "mail_compose module is not installed")
        composer = env["mail.compose.message"].browse(composer_id)
        if not composer._ids:
            raise HTTPException(404, f"mail.compose.message({composer_id}) not found")
        form = await request.form()
        # Honour any subject the operator just typed but hasn't saved.
        for key in ("subject", "body_html"):
            val = form.get(key)
            if val is not None:
                composer.write({key: val})
        name = (composer.subject or "Untitled template").strip() or "Untitled template"
        try:
            composer.action_save_as_template(name=name)
            message = f"Saved as template {name!r}"
        except Exception as exc:  # noqa: BLE001
            message = f"Save failed: {exc}"
        return HTMLResponse(
            _compose_form_html(env, composer.id),
            headers={"HX-Trigger": _json.dumps({"pv-toast": message})},
        )

    # ---------------------------------------------------------------
    # File library upload + picker (file_manager module)
    # ---------------------------------------------------------------

    def _upload_folder_context(env, folder_id: int | None) -> tuple[int | None, str]:
        """Resolve folder_id + human label for upload UI."""
        if not folder_id or folder_id <= 0:
            return None, "Unfiled"
        if "res.attachment.folder" not in registry:
            return None, "Unfiled"
        rec = _folder_or_404(env, int(folder_id))
        return rec.id, rec.name

    def _file_manager_render(
        env,
        request,
        *,
        error: str | None = None,
        folder_id: int | None = None,
    ):
        from .render import _env as render_env, merge_template_context

        fid, label = _upload_folder_context(env, folder_id)
        template = render_env.get_template("file_manager_upload.html")
        ctx = merge_template_context(
            env,
            str(request.url.path),
            error=error,
            folder_id=fid,
            folder_label=label,
            # The upload form is multipart, so the CSRF middleware's
            # body-parse fallback can't run (it skips multipart on
            # purpose to avoid buffering large uploads). The template
            # echoes the token in the form's action query string —
            # the middleware accepts ``?_csrf=…`` as a fallback.
            csrf_token=getattr(request.state, "csrf_token", ""),
        )
        return template.render(**ctx)

    def _parse_upload_folder_id(raw) -> int | None:
        """Normalize folder_id from form/query — ``0`` / empty → None (unfiled)."""
        if raw in (None, "", 0, "0"):
            return None
        return int(raw)

    def _store_uploaded_file(
        env,
        file: UploadFile,
        *,
        public: bool,
        res_model: str | None = None,
        res_id: int | None = None,
        folder_id: int | None = None,
    ) -> dict:
        """Persist one ``UploadFile`` into ``ir.attachment`` and return its row dict.

        Shared by the library Upload page and the file-picker dialog so the
        bytes-to-attachment path is one well-tested implementation.
        """
        import mimetypes as _mimetypes

        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")
        from .storage import get_backend

        backend = get_backend()
        original_name = file.filename or "file"
        storage_key = backend.save(original_name, content)
        datas = (
            base64.b64encode(content).decode("ascii")
            if not storage_key
            else None
        )
        mimetype = (
            file.content_type
            or _mimetypes.guess_type(original_name)[0]
            or "application/octet-stream"
        )
        vals: dict = {
            "name": original_name,
            "datas_fname": original_name,
            "mimetype": mimetype,
            "file_size": len(content),
            "res_model": res_model or None,
            "res_id": res_id if res_id else None,
            "type": "binary",
            "storage_key": storage_key,
            "datas": datas,
            "public": bool(public),
        }
        # Stamp the active company so the library / picker can scope by it.
        if "company_id" in env["ir.attachment"]._fields and env.company_id:
            vals["company_id"] = env.company_id
        if folder_id:
            if "res.attachment.folder" not in registry:
                raise HTTPException(404, "file_manager is not installed")
            _folder_or_404(env, int(folder_id))
            vals["folder_id"] = int(folder_id)
        with env.transaction():
            att = env["ir.attachment"].create(vals)
        return {
            "id": att.id,
            "name": att.name,
            "mimetype": att.mimetype,
            "size": att.file_size,
        }

    @app.get("/web/files/upload_panel", response_class=HTMLResponse)
    def web_files_upload_panel(
        request: Request,
        env: Environment = Depends(get_env),
        folder_id: int | None = None,
    ):
        """Multipart upload form fragment for ``PvDialog`` from the library."""
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "create")
        fid, label = _upload_folder_context(env, folder_id)
        from .render import _env as render_env

        return HTMLResponse(
            render_env.get_template("file_manager_upload_panel.html").render(
                folder_id=fid,
                folder_label=label,
                csrf_token=getattr(request.state, "csrf_token", ""),
            )
        )

    @app.get("/web/files/upload", response_class=HTMLResponse)
    def web_files_upload_form(
        request: Request,
        env: Environment = Depends(get_env),
        folder_id: int | None = None,
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "create")
        return HTMLResponse(
            _file_manager_render(env, request, folder_id=folder_id)
        )

    @app.post("/web/files/upload", response_class=HTMLResponse)
    async def web_files_upload_submit(
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "create")
        form = await request.form()
        raw_public = form.get("public")
        public = str(raw_public or "").strip().lower() in ("1", "on", "true", "yes")
        target_folder = _parse_upload_folder_id(form.get("folder_id"))
        files = form.getlist("files")
        if not files:
            return HTMLResponse(
                _file_manager_render(
                    env,
                    request,
                    error="Pick at least one file.",
                    folder_id=target_folder,
                ),
                status_code=400,
            )
        try:
            for upload in files:
                # Starlette's multipart parser returns its own
                # ``starlette.datastructures.UploadFile``; FastAPI
                # re-exports a subclass, so a strict
                # ``isinstance(upload, fastapi.UploadFile)`` check
                # silently rejected every file (parent isn't an
                # instance of child). Filter out raw strings (empty
                # file inputs) instead, and duck-type the rest.
                if isinstance(upload, str) or not hasattr(upload, "filename"):
                    continue
                _store_uploaded_file(
                    env, upload, public=public, folder_id=target_folder
                )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("file upload failed")
            return HTMLResponse(
                _file_manager_render(
                    env,
                    request,
                    error=f"Upload failed: {exc}",
                    folder_id=target_folder,
                ),
                status_code=500,
            )
        dest = "/web/files/library"
        if target_folder:
            dest = f"{dest}?folder_id={target_folder}"
        return RedirectResponse(dest, status_code=303)

    @app.get("/web/files/picker", response_class=HTMLResponse)
    def web_files_picker(
        request: Request,
        env: Environment = Depends(get_env),
        accept: str = "",
        q: str = "",
        multi: int = 0,
        folder_id: int | None = None,
    ):
        """Picker dialog body for ``widget="file"`` / ``widget="files"``.

        Opens inside ``PvDialog`` (the caller passes
        ``url='/web/files/picker?accept=image/*'``). Returns an HTML
        fragment with a folder-navigable tile grid + breadcrumb +
        search + inline upload. Folder navigation after the first paint
        is client-side via ``/web/files/picker/browse``.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "read")
        accept = (accept or "").strip()
        query = (q or "").strip()
        browse = _file_manager_browse(
            env, folder_id=folder_id, accept=accept, query=query
        )
        from .render import _env as render_env

        tpl = render_env.get_template("widgets/file_picker.html")
        return HTMLResponse(
            tpl.render(
                browse=browse,
                accept=accept,
                q=query,
                multi=bool(int(multi)),
                can_upload=env.has_access("ir.attachment", "create"),
            )
        )

    @app.get("/web/files/picker/browse")
    def web_files_picker_browse(
        request: Request,
        env: Environment = Depends(get_env),
        accept: str = "",
        q: str = "",
        folder_id: int | None = None,
    ):
        """JSON browse payload used by the picker for folder navigation.

        Returns ``{folder_id, breadcrumb, folders, rows, searching}`` so
        the dialog's Alpine component can re-render in place — keeping
        any multi-select made in other folders.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "read")
        return _file_manager_browse(
            env,
            folder_id=folder_id,
            accept=(accept or "").strip(),
            query=(q or "").strip(),
        )

    @app.post("/web/files/picker/upload", status_code=201)
    async def web_files_picker_upload(
        request: Request,
        file: UploadFile = File(...),
        public: bool = Form(False),
        folder_id: int | None = Form(None),
        env: Environment = Depends(get_env),
    ):
        """Upload-and-return-row inside the picker dialog.

        Lets the operator drop a new file onto the picker without having
        to leave the dialog. Returns the row JSON so the picker's JS can
        select the new attachment immediately.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager module is not installed")
        env.check_access("ir.attachment", "create")
        target_folder = _parse_upload_folder_id(folder_id)
        return _store_uploaded_file(
            env, file, public=public, folder_id=target_folder
        )

    def _accept_mime_domain(accept: str) -> list:
        """Translate an HTML ``accept`` token list into mimetype clauses.

        ``"image/*,application/pdf"`` → an OR-joined domain fragment
        suitable for ``Model.search`` (Odoo-style ``|`` operators).
        """
        if not accept:
            return []
        tokens = [t.strip() for t in accept.split(",") if t.strip()]
        clauses: list = []
        for tok in tokens:
            if tok.endswith("/*"):
                clauses.append(("mimetype", "ilike", f"{tok[:-1]}%"))
            elif "/" in tok:
                clauses.append(("mimetype", "=", tok))
        if not clauses:
            return []
        if len(clauses) == 1:
            return clauses
        return ["|"] * (len(clauses) - 1) + clauses

    def _library_company_domain(env) -> list:
        """Scope library / picker attachment queries to the active company.

        Returns ``[("company_id", "=", cid)]`` when a company scope is
        active and ``ir.attachment`` carries the column (added by
        file_manager); otherwise ``[]`` (no scoping). System attachments
        without a company simply don't surface in the library UI.
        """
        if (
            env.company_id
            and "ir.attachment" in registry
            and "company_id" in env["ir.attachment"]._fields
        ):
            return [("company_id", "=", env.company_id)]
        return []

    def _attachment_to_row(r) -> dict:
        from .file_icons import file_icon_key

        mime = (r.mimetype or "").lower()
        return {
            "id": r.id,
            "name": r.name,
            "mimetype": r.mimetype or "",
            "size": r.file_size or 0,
            "thumbnail_url": (
                f"/api/attachment/{r.id}/download"
                if mime.startswith("image/")
                else ""
            ),
            # Coarse type key → the JS ``pvFileIcon`` map renders a glyph
            # for non-image files (pdf / doc / xls / zip / …).
            "icon": file_icon_key(r.mimetype, r.datas_fname or r.name),
        }

    def _file_manager_picker_rows(
        env, *, accept: str, query: str, limit: int = 60
    ) -> list[dict]:
        Att = env["ir.attachment"]
        domain: list = list(_library_company_domain(env))
        if query:
            # ``ilike`` takes the pattern verbatim — wrap for substring.
            domain.append(("name", "ilike", f"%{query}%"))
        domain.extend(_accept_mime_domain(accept))
        rows = Att.search(domain, limit=limit, order='"id" DESC')
        return [_attachment_to_row(r) for r in rows]

    def _folder_breadcrumb(env, folder_id: int | None) -> list[dict]:
        """Root→leaf chain of ``{id, name}`` for a folder, or ``[]`` at root."""
        if not folder_id or "res.attachment.folder" not in registry:
            return []
        Folder = env["res.attachment.folder"]
        chain: list[dict] = []
        cursor = Folder.browse(int(folder_id))
        for _ in range(32):
            if not cursor._ids:
                break
            chain.append({"id": cursor.id, "name": cursor.name})
            cursor = cursor.parent_id
            if not cursor or not cursor._ids:
                break
        chain.reverse()
        return chain

    def _file_manager_browse(
        env, *, folder_id: int | None, accept: str, query: str, limit: int = 120
    ) -> dict:
        """Folder-scoped browse payload for the picker dialog.

        - With a search ``query``: flat search across every file (no
          folders), matching desktop "search in this PC" behaviour.
        - Otherwise: the subfolders of ``folder_id`` (top-level when
          None) plus the files filed directly in it (Unfiled when None).
        """
        Att = env["ir.attachment"]
        if query:
            return {
                "folder_id": folder_id,
                "breadcrumb": [],
                "folders": [],
                "rows": _file_manager_picker_rows(
                    env, accept=accept, query=query, limit=limit
                ),
                "searching": True,
            }

        target = int(folder_id) if folder_id else None
        folders: list[dict] = []
        if "res.attachment.folder" in registry:
            Folder = env["res.attachment.folder"]
            subs = Folder.search(
                [("parent_id", "=", target)], order='"sequence" ASC, "name" ASC'
            )
            child_counts: dict[int, int] = {}
            for f in Folder.search([]):
                if f.parent_id:
                    child_counts[f.parent_id.id] = child_counts.get(f.parent_id.id, 0) + 1
            cdom = _library_company_domain(env)
            for f in subs:
                file_n = Att.search_count([("folder_id", "=", f.id)] + cdom)
                folders.append(
                    {
                        "id": f.id,
                        "name": f.name,
                        "child_count": child_counts.get(f.id, 0),
                        "file_count": file_n,
                    }
                )

        file_domain: list = [("folder_id", "=", target)]
        file_domain.extend(_library_company_domain(env))
        file_domain.extend(_accept_mime_domain(accept))
        rows = Att.search(file_domain, limit=limit, order='"id" DESC')
        return {
            "folder_id": target,
            "breadcrumb": _folder_breadcrumb(env, target),
            "folders": folders,
            "rows": [_attachment_to_row(r) for r in rows],
            "searching": False,
        }

    # ---------------------------------------------------------------
    # File library — folders, bulk actions, Drive-style library shell
    # ---------------------------------------------------------------

    def _properties_context(env, att_id: int, *, panel_only: bool) -> dict:
        """Build the template ctx for both Properties endpoints.

        Shared so the side-panel fragment and the full page show
        exactly the same metadata for the same record.
        """
        Att = env["ir.attachment"]
        att = Att.browse(int(att_id))
        if not att._ids:
            raise HTTPException(404, f"ir.attachment({att_id}) not found")
        env.check_access("ir.attachment", "read")
        mimetype = (att.mimetype or "").lower().split(";", 1)[0].strip()
        is_image = mimetype.startswith("image/")
        # Extension hint from the original filename or display name.
        source = (att.datas_fname or att.name or "").rsplit(".", 1)
        extension = source[1].lower() if len(source) == 2 and source[1] else ""
        dimensions = None
        if is_image:
            try:
                from .image_meta import read_image_dimensions

                payload = att.fetch_content()
                if payload:
                    dimensions = read_image_dimensions(payload, mimetype)
            except Exception:  # noqa: BLE001 — corrupt file → no dimensions
                dimensions = None
        owner_url = ""
        if att.res_model and att.res_id and att.res_model in registry:
            owner_url = f"/web/records/{att.res_id}?model={att.res_model}"
        folder_chain: list[dict] = []
        if att.folder_id and "res.attachment.folder" in registry:
            cursor = att.folder_id
            for _ in range(32):
                if not cursor or not cursor._ids:
                    break
                folder_chain.append({"id": cursor.id, "name": cursor.name})
                cursor = cursor.parent_id
            folder_chain.reverse()
        return {
            "att": att,
            "mimetype": mimetype,
            "is_image": is_image,
            "extension": extension,
            "dimensions": dimensions,
            "owner_url": owner_url,
            "folder_chain": folder_chain,
            "panel_only": panel_only,
        }

    @app.get("/web/files/{att_id}/properties", response_class=HTMLResponse)
    def web_files_properties(
        att_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        from .render import _env as render_env, merge_template_context

        ctx = _properties_context(env, att_id, panel_only=False)
        layout = merge_template_context(env, str(request.url.path))
        layout.update(ctx)
        return HTMLResponse(
            render_env.get_template("file_manager_properties.html").render(**layout)
        )

    @app.get("/web/files/{att_id}/properties_panel", response_class=HTMLResponse)
    def web_files_properties_panel(
        att_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Fragment variant — same template, ``panel_only=True``."""
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        from .render import _env as render_env

        ctx = _properties_context(env, att_id, panel_only=True)
        return HTMLResponse(
            render_env.get_template("file_manager_properties.html").render(**ctx)
        )

    @app.get("/web/files/library", response_class=HTMLResponse)
    def web_files_library(
        request: Request,
        env: Environment = Depends(get_env),
        folder_id: int | None = None,
        q: str = "",
    ):
        """Drive-style library shell: folder tree + file area + details panel.

        The file area is rendered client-side (Alpine) from the
        ``_file_manager_browse`` payload, so it supports the grid / tiles
        / details view switch, type-icon previews, multi-select, and
        drag-to-folder without leaning on the generic kanban renderer.
        ``folder_id=0`` keeps the "Unfiled" convention (loose files, no
        subfolder tiles — the client suppresses them for that node).
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry or "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("ir.attachment", "read")
        env.check_access("res.attachment.folder", "read")
        from .render import _env as render_env, merge_template_context

        query = (q or "").strip()
        if folder_id == 0:
            active, target = 0, None
        elif folder_id:
            active, target = int(folder_id), int(folder_id)
        else:
            active, target = None, None

        browse = _file_manager_browse(
            env, folder_id=target, accept="", query=query
        )
        files = browse["rows"]
        visible_ids = [int(r["id"]) for r in files]

        tree_payload = web_files_tree(request, env)  # type: ignore[arg-type]

        layout = merge_template_context(
            env,
            str(request.url.path),
            csrf_token=getattr(request.state, "csrf_token", ""),
        )
        layout.update(
            {
                "active_folder_id": active,
                "folder_tree": tree_payload["folders"],
                "unfiled_count": tree_payload["unfiled_count"],
                "files": files,
                "visible_ids": visible_ids,
                "query": query,
                "searching": browse.get("searching", False),
                "can_write": env.has_access("ir.attachment", "write"),
            }
        )
        return HTMLResponse(
            render_env.get_template("file_manager_library.html").render(**layout)
        )

    def _folder_or_404(env, folder_id: int):
        if "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        Folder = env["res.attachment.folder"]
        rec = Folder.browse(int(folder_id))
        if not rec._ids:
            raise HTTPException(404, f"res.attachment.folder({folder_id}) not found")
        return rec

    def _folder_chain_includes(env, ancestor_id: int, candidate_id: int) -> bool:
        """Return True if ``candidate_id`` is ``ancestor_id`` or a descendant.

        Used to reject cycles on folder-move: a folder cannot become its
        own ancestor. Walks up the candidate's parent chain (depth-capped
        at the same 32 levels the display_name computer uses).
        """
        if ancestor_id == candidate_id:
            return True
        Folder = env["res.attachment.folder"]
        cursor = Folder.browse(candidate_id)
        for _ in range(32):
            if not cursor._ids:
                return False
            parent = cursor.parent_id
            if not parent or not parent._ids:
                return False
            if parent.id == ancestor_id:
                return True
            cursor = parent
        return False

    @app.get("/web/files/tree")
    def web_files_tree(
        request: Request, env: Environment = Depends(get_env)
    ):
        """Flat folder list for the Library's left-side tree.

        The client tree-renders by parent_id. Counts are denormalised
        per folder so the tree can show ``Marketing (12)`` without a
        second round-trip.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("res.attachment.folder", "read")
        Folder = env["res.attachment.folder"]
        Att = env["ir.attachment"]
        # Folder is _company_scoped → this search is auto-filtered.
        rows = Folder.search([], order='"sequence" ASC, "name" ASC')
        # Pull attachment counts in one pass, scoped to the active
        # company so the tree tallies match the file area.
        counts: dict[int | None, int] = {}
        for att in Att.search(_library_company_domain(env)):
            counts[att.folder_id.id if att.folder_id else None] = counts.get(
                att.folder_id.id if att.folder_id else None, 0
            ) + 1
        # Child counts per folder.
        child_count: dict[int, int] = {}
        for r in rows:
            if r.parent_id:
                child_count[r.parent_id.id] = child_count.get(r.parent_id.id, 0) + 1
        return {
            "folders": [
                {
                    "id": r.id,
                    "name": r.name,
                    "parent_id": r.parent_id.id if r.parent_id else None,
                    "sequence": r.sequence,
                    "color": r.color or "",
                    "child_count": child_count.get(r.id, 0),
                    "file_count": counts.get(r.id, 0),
                }
                for r in rows
            ],
            "unfiled_count": counts.get(None, 0),
        }

    @app.post("/web/files/folders", status_code=201)
    async def web_files_folder_create(
        request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("res.attachment.folder", "create")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "name is required")
        parent_id = payload.get("parent_id") or None
        Folder = env["res.attachment.folder"]
        vals = {"name": name}
        if parent_id:
            _folder_or_404(env, int(parent_id))
            vals["parent_id"] = int(parent_id)
        with env.transaction():
            rec = Folder.create(vals)
        return {"id": rec.id, "name": rec.name, "parent_id": parent_id}

    @app.patch("/web/files/folders/{folder_id}")
    async def web_files_folder_patch(
        folder_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("res.attachment.folder", "write")
        rec = _folder_or_404(env, folder_id)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        vals: dict = {}
        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                raise HTTPException(400, "name cannot be empty")
            vals["name"] = name
        if "parent_id" in payload:
            new_parent = payload.get("parent_id")
            if new_parent in (None, "", 0):
                vals["parent_id"] = None
            else:
                new_parent_id = int(new_parent)
                _folder_or_404(env, new_parent_id)
                if _folder_chain_includes(env, rec.id, new_parent_id):
                    raise HTTPException(
                        400, "parent_id would create a folder cycle"
                    )
                vals["parent_id"] = new_parent_id
        if vals:
            with env.transaction():
                rec.write(vals)
        return {
            "id": rec.id,
            "name": rec.name,
            "parent_id": rec.parent_id.id if rec.parent_id else None,
        }

    @app.delete("/web/files/folders/{folder_id}", status_code=204, response_class=Response)
    def web_files_folder_delete(
        folder_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("res.attachment.folder", "unlink")
        rec = _folder_or_404(env, folder_id)
        # Empty-check: no child folders, no attachments.
        Folder = env["res.attachment.folder"]
        Att = env["ir.attachment"]
        if Folder.search([("parent_id", "=", rec.id)]):
            raise HTTPException(409, "Folder has subfolders — empty it first")
        if Att.search([("folder_id", "=", rec.id)]):
            raise HTTPException(409, "Folder has files — empty it first")
        with env.transaction():
            rec.unlink()
        return Response(status_code=204)

    @app.post("/web/files/move")
    async def web_files_move(
        request: Request, env: Environment = Depends(get_env)
    ):
        """Bulk move attachments into a folder (or to Unfiled)."""
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry or "res.attachment.folder" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("ir.attachment", "write")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        ids = [int(x) for x in payload.get("attachment_ids") or [] if x]
        folder_id = payload.get("folder_id")
        if folder_id not in (None, "", 0):
            _folder_or_404(env, int(folder_id))
            target = int(folder_id)
        else:
            target = None
        if not ids:
            return {"updated": 0}
        with env.transaction():
            for aid in ids:
                rec = env["ir.attachment"].browse(aid)
                if rec._ids:
                    rec.write({"folder_id": target})
        return {"updated": len(ids)}

    @app.post("/web/files/copy")
    async def web_files_copy(
        request: Request, env: Environment = Depends(get_env)
    ):
        """Duplicate attachments into a folder (or Unfiled).

        Each copy is an independent ``ir.attachment`` row with its own
        stored bytes (re-saved through the storage backend) so deleting
        the original never strands the copy. Needs ``create`` on
        ``ir.attachment``.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        env.check_access("ir.attachment", "create")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        ids = [int(x) for x in payload.get("attachment_ids") or [] if x]
        folder_id = payload.get("folder_id")
        if folder_id not in (None, "", 0):
            _folder_or_404(env, int(folder_id))
            target = int(folder_id)
        else:
            target = None
        if not ids:
            return {"copied": 0}
        from .storage import get_backend

        backend = get_backend()
        Att = env["ir.attachment"]
        copied = 0
        with env.transaction():
            for aid in ids:
                src = Att.browse(aid)
                if not src._ids:
                    continue
                name = src.name or "file"
                vals = {
                    "name": name,
                    "datas_fname": src.datas_fname or name,
                    "mimetype": src.mimetype,
                    "file_size": src.file_size,
                    "res_model": None,
                    "res_id": None,
                    "type": src.type or "binary",
                    "public": bool(src.public),
                    "folder_id": target,
                }
                if "company_id" in Att._fields:
                    vals["company_id"] = (
                        src.company_id.id if src.company_id else env.company_id
                    )
                if src.type == "url":
                    vals["url"] = src.url
                else:
                    # Re-store the bytes so the copy owns an independent
                    # blob (db backend: inline base64; local: a new key).
                    data = src.fetch_content()
                    storage_key = backend.save(name, data) if data else ""
                    vals["storage_key"] = storage_key
                    vals["datas"] = (
                        base64.b64encode(data).decode("ascii")
                        if (data and not storage_key)
                        else None
                    )
                Att.create(vals)
                copied += 1
        return {"copied": copied}

    def _attachments_or_403(env, ids: list[int], perm: str):
        env.check_access("ir.attachment", perm)
        Att = env["ir.attachment"]
        out = []
        for aid in ids:
            rec = Att.browse(int(aid))
            if rec._ids:
                out.append(rec)
        return out

    @app.post("/web/files/bulk/download")
    async def web_files_bulk_download(
        request: Request, env: Environment = Depends(get_env)
    ):
        """Stream a ZIP of every selected attachment.

        URL-typed rows are listed as ``<name>.url`` text shortcuts.
        Failures on a single row (e.g. missing blob) are skipped with a
        warning header rather than failing the whole archive.
        """
        import io
        import zipfile

        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        # Fall back to form-encoded for hidden-form submits (browser
        # zip downloads use a hidden form, not a JSON fetch).
        if not payload:
            form = await request.form()
            raw = form.get("ids") or ""
            ids = [int(x) for x in str(raw).split(",") if x.strip().isdigit()]
        else:
            ids = [int(x) for x in payload.get("ids") or [] if x]
        if not ids:
            raise HTTPException(400, "ids is required")
        recs = _attachments_or_403(env, ids, "read")
        buf = io.BytesIO()
        skipped = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            seen: dict[str, int] = {}
            for rec in recs:
                base_name = (rec.datas_fname or rec.name or f"attachment-{rec.id}").strip() or f"attachment-{rec.id}"
                # Disambiguate filename collisions inside the archive.
                count = seen.get(base_name, 0)
                seen[base_name] = count + 1
                arc_name = base_name if count == 0 else f"{count}-{base_name}"
                if rec.type == "url":
                    body = f"[InternetShortcut]\nURL={rec.url or ''}\n".encode()
                    zf.writestr(arc_name + ".url", body)
                    continue
                try:
                    data = rec.fetch_content()
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                if not data:
                    skipped += 1
                    continue
                zf.writestr(arc_name, data)
        archive_name = f"files-{len(recs)}.zip"
        headers = {
            "Content-Disposition": f'attachment; filename="{archive_name}"',
        }
        if skipped:
            headers["X-PV-Skipped"] = str(skipped)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers=headers,
        )

    @app.post("/web/files/bulk/delete", status_code=204, response_class=Response)
    async def web_files_bulk_delete(
        request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        ids = [int(x) for x in payload.get("ids") or [] if x]
        if not ids:
            raise HTTPException(400, "ids is required")
        recs = _attachments_or_403(env, ids, "unlink")
        with env.transaction():
            for rec in recs:
                rec.unlink()
        return Response(status_code=204)

    @app.post("/web/files/bulk/public")
    async def web_files_bulk_public(
        request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(404, "file_manager is not installed")
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        ids = [int(x) for x in payload.get("ids") or [] if x]
        public = bool(payload.get("public"))
        if not ids:
            raise HTTPException(400, "ids is required")
        recs = _attachments_or_403(env, ids, "write")
        with env.transaction():
            for rec in recs:
                rec.write({"public": public})
        return {"updated": len(recs)}

    @app.post("/web/switch-company")
    async def web_switch_company(
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Store the chosen company_id in a cookie and redirect back."""
        if env.uid is None:
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        raw = (form.get("company_id") or "").strip()
        from .home import home_url

        redirect_to = request.headers.get("referer") or home_url()
        response = RedirectResponse(redirect_to, status_code=303)
        if raw:
            try:
                cid = int(raw)
            except ValueError:
                cid = None
            if cid is not None:
                response.set_cookie(
                    _COMPANY_COOKIE,
                    str(cid),
                    **auth_cookie,
                )
            else:
                response.delete_cookie(_COMPANY_COOKIE, path="/")
        else:
            response.delete_cookie(_COMPANY_COOKIE, path="/")
        return response

    @app.get("/web/companies")
    def web_list_companies(env: Environment = Depends(get_env)):
        """JSON list of available companies. Requires authentication."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if "res.company" not in registry:
            return {"companies": []}
        recs = env.with_company(None).sudo()["res.company"].search([])
        return {
            "current_company_id": env.company_id,
            "companies": [{"id": r.id, "name": r.name} for r in recs],
        }

    # ---- admin password reset (for another user) ----

    @app.get("/web/users/{user_id}/reset-password", response_class=HTMLResponse)
    def admin_password_reset_page(
        user_id: int, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _login_redirect(request)
        if "res.users" not in env.registry:
            raise HTTPException(503, "User model not loaded")
        Users = env["res.users"]
        # ACL: rely on res.users.read — non-admins fail here with 403.
        if not Users.search([("id", "=", user_id)]):
            raise HTTPException(404, f"res.users({user_id}) not found")
        user = Users.browse(user_id)
        from .render import render_admin_password_reset_page

        return HTMLResponse(
            render_admin_password_reset_page(
                env,
                user,
                current_path=str(request.url.path),
                csrf_token=request.state.csrf_token,
            )
        )

    @app.post("/web/users/{user_id}/reset-password", response_class=HTMLResponse)
    async def admin_password_reset_submit(
        user_id: int, request: Request, env: Environment = Depends(get_env)
    ):
        if env.uid is None:
            return _auth_required_response(request)
        if "res.users" not in env.registry:
            raise HTTPException(503, "User model not loaded")
        from .render import render_admin_password_reset_page

        Users = env["res.users"]
        if not Users.search([("id", "=", user_id)]):
            raise HTTPException(404, f"res.users({user_id}) not found")
        user = Users.browse(user_id)

        form = await request.form()
        new = form.get("new_password") or ""
        confirm = form.get("confirm_password") or ""

        def reject(msg: str) -> HTMLResponse:
            return HTMLResponse(
                render_admin_password_reset_page(
                    env,
                    user,
                    current_path=str(request.url.path),
                    csrf_token=request.state.csrf_token,
                    error=msg,
                ),
                status_code=422,
            )

        if not new or len(new) < 6:
            return reject("Password must be at least 6 characters.")
        if new != confirm:
            return reject("Password and confirmation do not match.")
        # The write itself is what enforces "must be admin" — ACL
        # checks ``perm_write`` on res.users, which only admin-group
        # users hold by default. We don't pre-gate on uid==1 because
        # delegating to ACL keeps the admin-group story extensible
        # (e.g. a future "User Manager" sub-group).
        with env.transaction():
            user.write({"password": str(new)})
        # Invalidate any active sessions the affected user has — a
        # password reset should kick them out so they re-authenticate
        # with the new credential. Same convention as Odoo.
        from pyvelm.session_auth import uses_stateless_sessions

        if not uses_stateless_sessions():
            with env.transaction():
                user.sudo().write({"session_token": None})

        return HTMLResponse(
            render_admin_password_reset_page(
                env,
                user,
                current_path=str(request.url.path),
                csrf_token=request.state.csrf_token,
                success=True,
            )
        )

    # ---- self-service account profile ----

    @app.get("/web/account/profile", response_class=HTMLResponse)
    def account_profile_page(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_account_profile_page

        return HTMLResponse(
            render_account_profile_page(
                env,
                current_path=str(request.url.path),
            )
        )

    @app.post("/web/account/profile", response_class=HTMLResponse)
    async def account_profile_submit(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_account_profile_page

        form = await request.form()
        name = (form.get("name") or "").strip()
        avatar_url = (form.get("avatar_url") or "").strip()

        def reject(msg: str, *, status: int = 422) -> HTMLResponse:
            return HTMLResponse(
                render_account_profile_page(
                    env,
                    current_path=str(request.url.path),
                    error=msg,
                    form_overrides={"name": name, "avatar_url": avatar_url},
                ),
                status_code=status,
            )

        if not name:
            return reject("Display name is required.")

        # sudo: self-service write — a user may edit their own profile
        # even without an explicit res.users write grant.
        vals: dict = {"name": name}
        if avatar_url:
            vals["avatar_url"] = avatar_url
        elif (form.get("avatar_url_clear") or "").strip().lower() in (
            "1",
            "true",
            "on",
            "yes",
        ):
            vals["avatar_url"] = None

        try:
            with env.transaction():
                env.sudo()["res.users"].browse(env.uid).write(vals)
        except (PermissionError, ValueError) as exc:
            return reject(str(exc) or "Could not update profile.")

        return HTMLResponse(
            render_account_profile_page(
                env,
                current_path=str(request.url.path),
                success=True,
            )
        )

    # ---- self-service password change ----

    @app.get("/web/account/password", response_class=HTMLResponse)
    def password_page(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_password_page

        return HTMLResponse(
            render_password_page(
                env,
                current_path=str(request.url.path),
            )
        )

    @app.post("/web/account/password", response_class=HTMLResponse)
    async def password_submit(request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_password_page

        form = await request.form()
        current = form.get("current_password") or ""
        new = form.get("new_password") or ""
        confirm = form.get("confirm_password") or ""

        # Verify the current password under sudo so even users without
        # explicit read on res.users (their own row included) can
        # still self-serve.
        user = env.sudo()["res.users"].browse(env.uid)
        current_ok = user.check_password(str(current))

        def reject(msg: str) -> HTMLResponse:
            return HTMLResponse(
                render_password_page(
                    env,
                    current_path=str(request.url.path),
                    error=msg,
                ),
                status_code=422,
            )

        if not current_ok:
            return reject("Current password is incorrect.")
        if not new or len(new) < 6:
            return reject("New password must be at least 6 characters.")
        if new != confirm:
            return reject("New password and confirmation do not match.")
        if new == current:
            return reject("New password must differ from the current one.")

        # Rotate the session token along with the password write so any
        # other browser session holding the old token is ejected on its
        # next request. The current session stays alive — we mint a
        # fresh token, persist it in the same atomic write, and refresh
        # the cookie on the response below.
        from pyvelm.session_auth import establish_session, uses_stateless_sessions

        if uses_stateless_sessions():
            with env.transaction():
                env.sudo()["res.users"].browse(env.uid).write({"password": new})
            new_token = establish_session(env, env.uid)
        else:
            new_token = secrets.token_hex(32)
            with env.transaction():
                env.sudo()["res.users"].browse(env.uid).write({
                    "password": new,
                    "session_token": new_token,
                })
        response = HTMLResponse(
            render_password_page(
                env,
                current_path=str(request.url.path),
                success=True,
            )
        )
        response.set_cookie(_SESSION_COOKIE, new_token, **session_cookie)
        return response

    # ---- login / logout ----

    @app.get("/web/database/selector", response_class=HTMLResponse)
    def database_selector_page(request: Request):
        if not routing_enabled(app):
            return RedirectResponse("/login", status_code=302)
        options = "".join(
            f'<option value="{key}">{label}</option>'
            for key, label in list_selectable_databases(app)
        )
        body = (
            "<!DOCTYPE html><html><head><title>Select database</title>"
            '<link rel="stylesheet" href="/web/static/css/app.css"></head>'
            '<body class="min-h-screen flex items-center justify-center bg-slate-50">'
            '<div class="w-full max-w-md p-8 bg-white shadow rounded-lg">'
            "<h1 class=\"text-xl font-semibold mb-4\">Select database</h1>"
            '<form method="post" action="/web/database/select">'
            f'<label class="block mb-2 text-sm">Database</label>'
            f'<select name="db" class="w-full border rounded px-3 py-2 mb-4">{options}</select>'
            '<button type="submit" class="w-full bg-indigo-600 text-white py-2 rounded">Continue</button>'
            "</form></div></body></html>"
        )
        return HTMLResponse(body)

    @app.post("/web/database/select")
    async def database_selector_submit(request: Request):
        from pyvelm.database_routing import DEFAULT_DB_KEY

        if not routing_enabled(app):
            return RedirectResponse("/login", status_code=302)
        form = await request.form()
        key = (form.get("db") or DEFAULT_DB_KEY).strip()
        pool_map = getattr(app.state, "pool_map", None) or {}
        if key not in pool_map:
            raise HTTPException(status_code=400, detail=f"Unknown database {key!r}")
        response = RedirectResponse("/login", status_code=303)
        response.set_cookie(DATABASE_COOKIE, key, path="/", **auth_cookie)
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = Query(default="")):
        from .home import login_destination
        from .render import render_login_page

        # Already authenticated and the token is valid? Skip the login screen.
        token = request.cookies.get(_SESSION_COOKIE)
        with _active_pool(request).connection() as conn:
            env = Environment(conn, registry=_active_registry(request), uid=None)
            if token and _resolve_user_from_session(env, token) is not None:
                return RedirectResponse(
                    login_destination(next), status_code=302
                )
            raw_co = request.cookies.get(_COMPANY_COOKIE)
            if raw_co:
                try:
                    env = env.with_company(int(raw_co))
                except (TypeError, ValueError):
                    pass
            return HTMLResponse(
                render_login_page(
                    next=next,
                    csrf_token=request.state.csrf_token,
                    env=env,
                )
            )

    # ── /login rate limit ──
    # Per-IP sliding window. 5 attempts per 5 minutes; the 6th gets
    # 429 + Retry-After. In-memory, so it's per-process — multi-worker
    # deployments (gunicorn -w N) effectively multiply the limit by
    # the worker count. Real production setups put a shared store
    # (Redis, the reverse proxy's own rate limiter) in front; this
    # is good enough for the dev server + small single-process
    # deployments.
    _LOGIN_RATE_WINDOW = 300  # seconds
    _LOGIN_RATE_MAX = 5
    _login_attempts: dict[str, list[float]] = {}

    def _check_login_rate(ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - _LOGIN_RATE_WINDOW
        attempts = _login_attempts.setdefault(ip, [])
        attempts[:] = [t for t in attempts if t > cutoff]
        if len(attempts) >= _LOGIN_RATE_MAX:
            retry = int(attempts[0] + _LOGIN_RATE_WINDOW - now)
            return False, max(retry, 1)
        attempts.append(now)
        return True, 0

    app.state.login_attempts = _login_attempts  # for tests

    @app.post("/login")
    async def login_submit(request: Request):
        from .render import render_login_page

        client_host = request.client.host if request.client else "unknown"
        ok, retry_after = _check_login_rate(client_host)
        if not ok:
            return _render_styled_error(
                request,
                429,
                message=(
                    "Too many sign-in attempts from this address. "
                    "Please wait before trying again."
                ),
                retry_after=retry_after,
            )

        form = await request.form()
        login_val = (form.get("login") or "").strip()
        password_val = form.get("password") or ""
        from .home import login_destination

        next_url = login_destination((form.get("next") or "").strip())

        # Validate credentials.
        with _active_pool(request).connection() as conn:
            env = Environment(conn, registry=_active_registry(request), uid=None)
            # sudo: credential validation runs before any user is bound,
            # so it must read res.users without ACL.
            senv = env.sudo()
            if "res.users" not in env.registry:
                raise HTTPException(503, "User model not loaded")
            users = senv["res.users"].search(
                [("login", "=", login_val), ("active", "=", True)], limit=1
            )
            if not users or not users.check_password(password_val):
                theme_env = senv
                raw_co = request.cookies.get(_COMPANY_COOKIE)
                if raw_co:
                    try:
                        theme_env = senv.with_company(int(raw_co))
                    except (TypeError, ValueError):
                        theme_env = senv
                return HTMLResponse(
                    render_login_page(
                        error="Invalid username or password.",
                        next=next_url,
                        prefill_login=login_val,
                        csrf_token=request.state.csrf_token,
                        env=theme_env,
                    ),
                    status_code=401,
                )
            uid = users.id
            from pyvelm.session_auth import establish_session

            token = establish_session(senv, uid)
            # Capture the user's home company so we can pre-set the
            # company-scope cookie below. Reads through sudo so a user
            # without explicit access to res.users on their own row
            # still resolves the FK.
            home_company = users.company_id
            home_company_id = home_company.id if home_company else None

        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(_SESSION_COOKIE, token, **session_cookie)
        # Default the active company to the user's home company. Without
        # this, a freshly-logged-in user lands on /web/admin with no
        # scope selected and the multi-company filter is invisible until
        # they click the switcher — surprising UX. The switcher can still
        # override or clear this cookie post-login.
        if home_company_id is not None:
            response.set_cookie(
                _COMPANY_COOKIE,
                str(home_company_id),
                **auth_cookie,
            )
        else:
            response.delete_cookie(_COMPANY_COOKIE, path="/")
        return response

    @app.post("/logout")
    def logout(request: Request):
        from pyvelm.session_auth import revoke_session

        token = request.cookies.get(_SESSION_COOKIE)
        if token:
            with _active_pool(request).connection() as conn:
                env = Environment(
                    conn, registry=_active_registry(request), uid=None,
                )
                revoke_session(env, token)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(_SESSION_COOKIE, path="/")
        response.delete_cookie(_COMPANY_COOKIE, path="/")
        # Wipe the browser back-forward cache so hitting "Back" after
        # logout doesn't reveal the previously-rendered authenticated
        # page. `Clear-Site-Data: "cache"` evicts bfcache entries in
        # browsers that honor it; `cookies` is belt-and-suspenders to
        # the explicit delete_cookie calls above.
        response.headers["Clear-Site-Data"] = '"cache", "cookies"'
        return response

    # ---- Attachment upload / download --------------------------------------

    @app.post("/api/attachment/upload", status_code=201)
    def upload_attachment(
        request: Request,
        file: UploadFile = File(...),
        res_model: str | None = Form(None),
        res_id: int | None = Form(None),
        public: bool = Form(False),
        env: Environment = Depends(get_env),
    ):
        """Persist an uploaded blob into ``ir.attachment``.

        Multipart form fields:
          file       The uploaded file (required).
          res_model  Owning model name (e.g. ``crm.lead``). Optional —
                     omit when uploading to a not-yet-saved record; the
                     widget patches ``res_id`` on parent-form save.
          res_id     Primary key of the owning record. Same caveat.
          public     ``True`` for UI-chrome images (logos, avatars) that
                     must be served without an ``ir.attachment`` read
                     grant. The image widget sets this; the document
                     uploader leaves it ``False``.

        Returns JSON with the new row's ``{id, name, mimetype, size}``.
        """
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(
                status_code=503, detail="ir.attachment model not loaded"
            )
        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        from .storage import get_backend
        backend = get_backend()
        original_name = file.filename or "file"
        storage_key = backend.save(original_name, content)
        # The DB backend returns "" and expects the bytes inline in
        # the row; the local backend returns a key and skips datas.
        datas = (
            base64.b64encode(content).decode("ascii")
            if not storage_key
            else None
        )
        # MIME comes from the client's Content-Type with a server-side
        # extension fallback for clients that send nothing useful.
        import mimetypes
        mimetype = (
            file.content_type
            or mimetypes.guess_type(original_name)[0]
            or "application/octet-stream"
        )
        with env.transaction():
            att = env["ir.attachment"].create({
                "name": original_name,
                "datas_fname": original_name,
                "mimetype": mimetype,
                "file_size": len(content),
                "res_model": res_model or None,
                "res_id": res_id if res_id else None,
                "type": "binary",
                "storage_key": storage_key,
                "datas": datas,
                "public": bool(public),
            })
        return {
            "id": att.id,
            "name": att.name,
            "mimetype": att.mimetype,
            "size": att.file_size,
        }

    @app.get("/api/attachment/{att_id}/download")
    def download_attachment(
        att_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Stream a single attachment's bytes back as a file download.

        ``Content-Disposition: attachment`` plus the original filename
        triggers a browser download; the widget links to this URL
        directly so users get save-as semantics."""
        if "ir.attachment" not in registry:
            raise HTTPException(
                status_code=503, detail="ir.attachment model not loaded"
            )
        # Probe existence + the public flag under sudo (cheap, leaks
        # nothing). `public` attachments are UI chrome — logos, favicons,
        # avatars, inline images referenced from rendered pages — so the
        # bytes are served to anyone, even an anonymous session (the
        # login-screen logo). Anything else stays behind the normal
        # login + `ir.attachment` read check.
        probe = env.sudo()["ir.attachment"].search(
            [("id", "=", att_id)], limit=1
        )
        if not probe:
            raise HTTPException(status_code=404, detail="Attachment not found")
        if probe.public:
            att = probe  # already a sudo-bound singleton
        else:
            if env.uid is None:
                return _auth_required_response(request)
            # Enforced env: reading the fields below runs the normal
            # check_access("ir.attachment", "read").
            att = env["ir.attachment"].browse(att_id)
        att.ensure_one()
        if att.type == "url":
            # External link — bounce the browser there rather than
            # streaming nothing.
            return RedirectResponse(att.url, status_code=302)
        content = att.fetch_content()
        filename = att.datas_fname or att.name or f"attachment-{att.id}"
        # Quote double-quotes in the filename to keep the header valid.
        safe_filename = filename.replace('"', "")
        cache = "public" if probe.public else "private"
        return Response(
            content,
            media_type=att.mimetype or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
                # Cache by id (immutable once written) so repeated views
                # of a form don't re-download.
                "Cache-Control": f"{cache}, max-age=3600",
            },
        )

    @app.delete("/api/attachment/{att_id}", status_code=204, response_class=Response)
    def delete_attachment(
        att_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        """Remove an attachment row and its backing blob."""
        if env.uid is None:
            return _auth_required_response(request)
        if "ir.attachment" not in registry:
            raise HTTPException(
                status_code=503, detail="ir.attachment model not loaded"
            )
        att = env["ir.attachment"].browse(att_id)
        if not att:
            raise HTTPException(status_code=404, detail="Attachment not found")
        with env.transaction():
            att.unlink()
        return Response(status_code=204)

    from .loader import register_web_routes

    register_web_routes(app, app.state.module_roots)

    return app
