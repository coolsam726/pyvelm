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
import secrets
from typing import Any

import base64
import binascii

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .env import Environment
from .fields import Many2many, Many2one, One2many
from .registry import Registry


def _display_value(record) -> str:
    """Best-effort short label for a Many2one render.

    Tries `display_name` (Odoo convention) then `name`, then `str(id)`.
    Doesn't trigger a search — just reads from the cache via the
    descriptor, accepting that this hits the DB if the cache misses.
    """
    if not record:
        return ""
    for attr in ("display_name", "name"):
        if attr in record._fields:
            try:
                value = getattr(record, attr)
                if value is not None:
                    return str(value)
            except Exception:  # noqa: BLE001
                pass
    return str(record.id)


def serialize_record(record, fields: list[str] | None = None) -> dict[str, Any]:
    """Convert a singleton recordset into a JSON-friendly dict.

    Many2one => [id, display_value]. One2many/Many2many => list of ids.
    Scalars pass through. `id` is always included.
    """
    record.ensure_one()
    model_cls = type(record)
    if fields is None:
        fields = [
            f for f, fld in model_cls._fields.items() if fld.is_stored
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


def create_app(registry: Registry, pool: Any,
               module_roots: list | None = None) -> FastAPI:
    """Build the FastAPI app bound to a loaded registry and a Postgres
    connection pool. Each request checks out a connection, makes an
    Environment, and returns it on exit. The pool's own retry/backoff
    handles transient failures.

    `module_roots` is the same list passed to `loader.load_and_install`
    so the Apps catalog page can re-discover the disk-side manifests.
    Optional — if omitted, the catalog page reports "no roots configured"
    instead of crashing.

    `pool` is typed `Any` because `psycopg_pool.ConnectionPool` is generic
    over the connection class and propagating that here adds friction
    without buying meaningful type safety — every method we call on it
    is on the runtime type."""

    app = FastAPI(title="pyvelm")
    app.state.module_roots = list(module_roots or [])

    # Prevent browsers from caching authenticated pages.  Without this
    # header the back-button serves a stale cached copy after logout.
    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            path = request.url.path
            # Apply to all /web/ HTML routes except static assets.
            if path.startswith("/web/") and not path.startswith("/web/static"):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
                response.headers["Pragma"] = "no-cache"
            return response

    app.add_middleware(NoCacheMiddleware)

    @app.exception_handler(PermissionError)
    def _permission_error(request, exc):
        msg = str(exc)
        # Anonymous failures get 401 + WWW-Authenticate so browsers
        # prompt for credentials; authenticated-but-denied is 403.
        if "anonymous" in msg or "uid=None" in msg:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="pyvelm"'},
                content=msg,
            )
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
        if not token or "res.users" not in registry:
            return None
        env._acl_bypass = True
        try:
            users = env["res.users"].search(
                [("session_token", "=", token), ("active", "=", True)], limit=1
            )
            if not users:
                return None
            users.ensure_one()
            return users.id
        finally:
            env._acl_bypass = False

    def _resolve_user_from_basic(env: Environment, header_value: str | None) -> int | None:
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
        if "res.users" not in registry:
            return None
        # Bypass ACL on the user lookup itself.
        env._acl_bypass = True
        try:
            users = env["res.users"].search(
                [("login", "=", login), ("active", "=", True)], limit=1,
            )
            if not users:
                return None
            user = users
            user.ensure_one()
            if not user.check_password(password):
                return None
            return user.id
        finally:
            env._acl_bypass = False

    def get_env(request: Request):
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            # Session cookie takes priority; fall back to HTTP Basic auth.
            uid = _resolve_user_from_session(
                env, request.cookies.get(_SESSION_COOKIE)
            )
            if uid is None:
                uid = _resolve_user_from_basic(
                    env, request.headers.get("authorization")
                )
            if uid is not None:
                env.uid = uid
                # Drop caches keyed on the previous (None) uid.
                env._user_groups_cache = None  # type: ignore[attr-defined]
                env._access_cache.clear()
            # Thread company scope from dedicated cookie.
            raw_company = request.cookies.get(_COMPANY_COOKIE)
            if raw_company:
                try:
                    env = env.with_company(int(raw_company))
                except (ValueError, TypeError):
                    pass  # malformed cookie — ignore; effectively no scope
            yield env

    def _load_view(env, module: str, name: str):
        if "ir.ui.view" not in registry:
            raise HTTPException(
                status_code=503, detail="No ir.ui.view model loaded"
            )
        View = env["ir.ui.view"]
        rec = View.search([("module", "=", module), ("name", "=", name)])
        if not rec:
            raise HTTPException(
                status_code=404, detail=f"View {module}/{name} not found"
            )
        rec.ensure_one()
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
        page_size: int = Query(default=20, ge=1, le=200),
        search: str = Query(default=""),
        order: str = Query(default=""),
        filters: str = Query(default=""),
        group_by: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_kanban_page, render_list_page

        rec = _load_view(env, module, name)
        path = str(request.url.path)
        if rec.view_type == "list":
            return HTMLResponse(
                render_list_page(
                    rec, env, page=page, page_size=page_size,
                    search=search, order=order, filters=filters,
                    group_by=group_by, current_path=path
                )
            )
        if rec.view_type == "kanban":
            return HTMLResponse(render_kanban_page(rec, env, current_path=path))
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
        page: int = Query(default=0, ge=0),
        page_size: int = Query(default=20, ge=1, le=200),
        search: str = Query(default=""),
        order: str = Query(default=""),
        filters: str = Query(default=""),
        group_by: str = Query(default=""),
        env: Environment = Depends(get_env),
    ):
        """HTML fragment endpoint used by HTMX `load more` swaps."""
        if env.uid is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        from .render import render_list_rows

        rec = _load_view(env, module, name)
        if rec.view_type != "list":
            raise HTTPException(
                status_code=501,
                detail=f"Renderer for view_type {rec.view_type!r} not yet shipped",
            )
        return HTMLResponse(
            render_list_rows(
                rec, env, page=page, page_size=page_size,
                search=search, order=order, filters=filters,
                group_by=group_by,
            )
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
            "results": [
                {"id": r.id, "label": _display_value(r)} for r in recs
            ],
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
            raise HTTPException(
                status_code=404, detail=f"Unknown model {model!r}"
            )
        domain_parsed = _parse_domain(domain)
        field_list = [f.strip() for f in fields.split(",") if f.strip()] or None
        Model = env[model]
        recs = Model.search(
            domain_parsed, limit=limit, offset=offset, order=order
        )
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
    def web_row_new(module: str, name: str, request: Request, env: Environment = Depends(get_env)):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_new_row

        view = _load_view(env, module, name)
        return HTMLResponse(render_new_row(view, env))

    @app.get("/web/records/{module}/{name}/row/{record_id}",
             response_class=HTMLResponse)
    def web_row_display(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    @app.get("/web/records/{module}/{name}/row/{record_id}/edit",
             response_class=HTMLResponse)
    def web_row_edit(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        return HTMLResponse(render_list_row(view, rec, env, mode="edit"))

    @app.post("/web/records/{module}/{name}/row/{record_id}",
              response_class=HTMLResponse)
    async def web_row_save(
        module: str, name: str, record_id: int, request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form)
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

    @app.delete("/web/records/{module}/{name}/row/{record_id}",
                response_class=HTMLResponse)
    def web_row_delete(
        module: str, name: str, record_id: int,
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
        module: str, name: str, request: Request,
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

    @app.post("/web/records/{module}/{name}", response_class=HTMLResponse)
    async def web_row_create(
        module: str, name: str, request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        cls = env.registry[view.model]
        form = await request.form()
        vals, errors = parse_form_vals(cls, form)
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
            raise HTTPException(
                400, f"View {rec.module}.{rec.name} is not a form view"
            )
        return rec

    @app.get("/web/views/{module}/{name}/new", response_class=HTMLResponse)
    def web_form_new(
        module: str, name: str, request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        return HTMLResponse(
            render_form_page(view, None, env, mode="new",
                             current_path=str(request.url.path))
        )

    @app.get("/web/views/{module}/{name}/record/{record_id}",
             response_class=HTMLResponse)
    def web_form_display(
        module: str, name: str, record_id: int,
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
            render_form_page(view, rec, env, mode="display",
                             body_only=body_only,
                             current_path=str(request.url.path))
        )

    @app.get("/web/views/{module}/{name}/record/{record_id}/edit",
             response_class=HTMLResponse)
    def web_form_edit(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _login_redirect(request)
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(view, rec, env, mode="edit",
                             body_only=body_only,
                             current_path=str(request.url.path))
        )

    @app.post("/web/views/{module}/{name}/record/{record_id}",
              response_class=HTMLResponse)
    async def web_form_save(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form)
        body_only = request.headers.get("HX-Request") == "true"
        if errors:
            # Parse-side validation failed. Re-render the edit form with
            # per-field messages stamped + the user's typed values
            # resurrected so they don't have to retype.
            return HTMLResponse(
                render_form_page(view, rec, env, mode="edit",
                                 body_only=body_only,
                                 errors=errors, submitted=vals,
                                 current_path=str(request.url.path)),
                status_code=422,
            )
        try:
            with env.transaction():
                rec.write(vals)
        except Exception as exc:  # noqa: BLE001
            # ORM-level failure (constraint, downstream DB error).
            # Show a top-level banner so the user sees why the save
            # didn't stick instead of getting a silent 500.
            return HTMLResponse(
                render_form_page(view, rec, env, mode="edit",
                                 body_only=body_only,
                                 submitted=vals,
                                 form_error=str(exc),
                                 current_path=str(request.url.path)),
                status_code=422,
            )
        env.cache.invalidate(model_name=view.model, ids=[record_id])
        return HTMLResponse(
            render_form_page(view, rec, env, mode="display",
                             body_only=body_only,
                             current_path=str(request.url.path))
        )

    @app.post("/web/views/{module}/{name}", response_class=HTMLResponse)
    async def web_form_create(
        module: str, name: str, request: Request,
        env: Environment = Depends(get_env),
    ):
        if env.uid is None:
            return _auth_required_response(request)
        from .render import parse_form_vals, render_form_page

        view = _require_form_view(_load_view(env, module, name))
        form = await request.form()
        cls = env.registry[view.model]
        vals, errors = parse_form_vals(cls, form)
        body_only = request.headers.get("HX-Request") == "true"
        if errors:
            return HTMLResponse(
                render_form_page(view, None, env, mode="new",
                                 body_only=body_only,
                                 errors=errors, submitted=vals,
                                 current_path=str(request.url.path)),
                status_code=422,
            )
        try:
            with env.transaction():
                rec = env[view.model].create(vals)
        except Exception as exc:  # noqa: BLE001
            return HTMLResponse(
                render_form_page(view, None, env, mode="new",
                                 body_only=body_only,
                                 submitted=vals,
                                 form_error=str(exc),
                                 current_path=str(request.url.path)),
                status_code=422,
            )
        return HTMLResponse(
            render_form_page(view, rec, env, mode="display",
                             body_only=body_only,
                             current_path=str(request.url.path))
        )

    # ---- admin dashboard ----

    @app.get("/web/admin", response_class=HTMLResponse)
    def web_admin(request: Request, env: Environment = Depends(get_env)):
        from .render import render_admin_page

        if env.uid is None:
            return RedirectResponse("/login?next=/web/admin", status_code=302)
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

    def _apps_action_response(request: Request, env: Environment,
                              result: dict) -> Response:
        """Convert an install/upgrade result into an HTMX response.

        HTMX clients get an empty body with `HX-Redirect: /web/apps`
        so the full page (including the sidebar) reloads — newly-
        installed modules may have added menu entries the cached
        chrome doesn't know about. Plain browser POSTs land on the
        same redirect via 303.
        """
        if request.headers.get("HX-Request") == "true":
            return Response(
                status_code=204,
                headers={"HX-Redirect": "/web/apps"},
            )
        return RedirectResponse("/web/apps", status_code=303)

    @app.post("/web/apps/{name}/install")
    def web_app_install(name: str, request: Request,
                        env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import install_module_action
        try:
            result = install_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

    @app.post("/web/apps/{name}/upgrade")
    def web_app_upgrade(name: str, request: Request,
                        env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import upgrade_module_action
        try:
            result = upgrade_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

    @app.get("/web/apps/{name}/uninstall-preview")
    def web_app_uninstall_preview(name: str, request: Request,
                                  env: Environment = Depends(get_env)):
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
    def web_app_uninstall(name: str, request: Request,
                          env: Environment = Depends(get_env)):
        if env.uid is None:
            return _auth_required_response(request)
        _require_admin(env)
        from .render import uninstall_module_action
        try:
            result = uninstall_module_action(env, app.state.module_roots, name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _apps_action_response(request, env, result)

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
        redirect_to = request.headers.get("referer") or "/web/admin"
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
                    httponly=True,
                    samesite="lax",
                    path="/",
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
        bypass_env = env.with_company(None)
        bypass_env._acl_bypass = True
        try:
            recs = bypass_env["res.company"].search([])
        finally:
            bypass_env._acl_bypass = False
        return {
            "current_company_id": env.company_id,
            "companies": [{"id": r.id, "name": r.name} for r in recs],
        }

    # ---- login / logout ----

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = Query(default="")):
        from .render import render_login_page

        # Already authenticated and the token is valid? Skip the login screen.
        token = request.cookies.get(_SESSION_COOKIE)
        if token:
            with pool.connection() as conn:
                env = Environment(conn, registry=registry, uid=None)
                if _resolve_user_from_session(env, token) is not None:
                    return RedirectResponse(next or "/web/admin", status_code=302)
        return HTMLResponse(render_login_page(next=next))

    @app.post("/login")
    async def login_submit(request: Request):
        from .render import render_login_page

        form = await request.form()
        login_val = (form.get("login") or "").strip()
        password_val = form.get("password") or ""
        next_url = (form.get("next") or "").strip() or "/web/admin"

        # Validate credentials.
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env._acl_bypass = True
            try:
                if "res.users" not in registry:
                    raise HTTPException(503, "User model not loaded")
                users = env["res.users"].search(
                    [("login", "=", login_val), ("active", "=", True)], limit=1
                )
                if not users or not users.check_password(password_val):
                    return HTMLResponse(
                        render_login_page(
                            error="Invalid username or password.",
                            next=next_url,
                            prefill_login=login_val,
                        ),
                        status_code=401,
                    )
                uid = users.id
                token = secrets.token_hex(32)
                with env.transaction():
                    users.write({"session_token": token})
                # Capture the user's home company so we can pre-set the
                # company-scope cookie below. Reads through the ACL bypass
                # so a user without explicit access to res.users on their
                # own row still resolves the FK.
                home_company = users.company_id
                home_company_id = home_company.id if home_company else None
            finally:
                env._acl_bypass = False

        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            httponly=True,
            samesite="lax",
            path="/",
        )
        # Default the active company to the user's home company. Without
        # this, a freshly-logged-in user lands on /web/admin with no
        # scope selected and the multi-company filter is invisible until
        # they click the switcher — surprising UX. The switcher can still
        # override or clear this cookie post-login.
        if home_company_id is not None:
            response.set_cookie(
                _COMPANY_COOKIE,
                str(home_company_id),
                httponly=True,
                samesite="lax",
                path="/",
            )
        else:
            response.delete_cookie(_COMPANY_COOKIE, path="/")
        return response

    @app.post("/logout")
    def logout(request: Request):
        token = request.cookies.get(_SESSION_COOKIE)
        if token:
            with pool.connection() as conn:
                env = Environment(conn, registry=registry, uid=None)
                env._acl_bypass = True
                try:
                    users = env["res.users"].search(
                        [("session_token", "=", token)], limit=1
                    )
                    if users:
                        with env.transaction():
                            users.write({"session_token": None})
                finally:
                    env._acl_bypass = False
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

    return app
