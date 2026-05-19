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
from typing import Any

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
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


def create_app(registry: Registry, pool: Any) -> FastAPI:
    """Build the FastAPI app bound to a loaded registry and a Postgres
    connection pool. Each request checks out a connection, makes an
    Environment, and returns it on exit. The pool's own retry/backoff
    handles transient failures.

    `pool` is typed `Any` because `psycopg_pool.ConnectionPool` is generic
    over the connection class and propagating that here adds friction
    without buying meaningful type safety — every method we call on it
    is on the runtime type."""

    app = FastAPI(title="pyvelm")

    # Static assets shipped inside the package (CSS, eventually images).
    from .render import STATIC_DIR
    app.mount(
        "/web/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="pyvelm-static",
    )

    def get_env():
        with pool.connection() as conn:
            env = Environment(conn, registry=registry)
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
        page: int = Query(default=0, ge=0),
        page_size: int = Query(default=20, ge=1, le=200),
        env: Environment = Depends(get_env),
    ):
        from .render import render_list_page

        rec = _load_view(env, module, name)
        if rec.view_type != "list":
            # Form views are addressed via /record/{id}; kanban is not
            # yet implemented. List is the only valid landing for the
            # bare view URL today.
            raise HTTPException(
                status_code=501,
                detail=(
                    f"view_type {rec.view_type!r} has no top-level page; "
                    f"use /record/{{id}} for form views"
                ),
            )
        return HTMLResponse(
            render_list_page(rec, env, page=page, page_size=page_size)
        )

    @app.get("/web/records/{module}/{name}", response_class=HTMLResponse)
    def web_view_rows(
        module: str,
        name: str,
        page: int = Query(default=0, ge=0),
        page_size: int = Query(default=20, ge=1, le=200),
        env: Environment = Depends(get_env),
    ):
        """HTML fragment endpoint used by HTMX `load more` swaps."""
        from .render import render_list_rows

        rec = _load_view(env, module, name)
        if rec.view_type != "list":
            raise HTTPException(
                status_code=501,
                detail=f"Renderer for view_type {rec.view_type!r} not yet shipped",
            )
        return HTMLResponse(
            render_list_rows(rec, env, page=page, page_size=page_size)
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

    @app.get("/web/records/{module}/{name}/new", response_class=HTMLResponse)
    def web_row_new(module: str, name: str, env: Environment = Depends(get_env)):
        from .render import render_new_row

        view = _load_view(env, module, name)
        return HTMLResponse(render_new_row(view, env))

    @app.get("/web/records/{module}/{name}/row/{record_id}",
             response_class=HTMLResponse)
    def web_row_display(
        module: str, name: str, record_id: int,
        env: Environment = Depends(get_env),
    ):
        from .render import render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    @app.get("/web/records/{module}/{name}/row/{record_id}/edit",
             response_class=HTMLResponse)
    def web_row_edit(
        module: str, name: str, record_id: int,
        env: Environment = Depends(get_env),
    ):
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
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals = parse_form_vals(cls, form)
        with env.transaction():
            rec.write(vals)
        # Reread for any computed-field follow-on values.
        env.cache.invalidate(model_name=view.model, ids=[record_id])
        return HTMLResponse(render_list_row(view, rec, env, mode="display"))

    @app.delete("/web/records/{module}/{name}/row/{record_id}",
                response_class=HTMLResponse)
    def web_row_delete(
        module: str, name: str, record_id: int,
        env: Environment = Depends(get_env),
    ):
        view = _load_view(env, module, name)
        rec = _load_record(env, view, record_id)
        with env.transaction():
            rec.unlink()
        return HTMLResponse("")

    @app.post("/web/records/{module}/{name}", response_class=HTMLResponse)
    async def web_row_create(
        module: str, name: str, request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import parse_form_vals, render_list_row

        view = _load_view(env, module, name)
        cls = env.registry[view.model]
        form = await request.form()
        vals = parse_form_vals(cls, form)
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
        module: str, name: str, env: Environment = Depends(get_env),
    ):
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        return HTMLResponse(render_form_page(view, None, env, mode="new"))

    @app.get("/web/views/{module}/{name}/record/{record_id}",
             response_class=HTMLResponse)
    def web_form_display(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        # HX-Request header set by HTMX -> return body fragment for
        # in-place swap; otherwise full page for direct navigation.
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(view, rec, env, mode="display", body_only=body_only)
        )

    @app.get("/web/views/{module}/{name}/record/{record_id}/edit",
             response_class=HTMLResponse)
    def web_form_edit(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(view, rec, env, mode="edit", body_only=body_only)
        )

    @app.post("/web/views/{module}/{name}/record/{record_id}",
              response_class=HTMLResponse)
    async def web_form_save(
        module: str, name: str, record_id: int,
        request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import parse_form_vals, render_form_page

        view = _require_form_view(_load_view(env, module, name))
        rec = _load_record(env, view, record_id)
        form = await request.form()
        cls = env.registry[view.model]
        vals = parse_form_vals(cls, form)
        with env.transaction():
            rec.write(vals)
        env.cache.invalidate(model_name=view.model, ids=[record_id])
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(view, rec, env, mode="display", body_only=body_only)
        )

    @app.post("/web/views/{module}/{name}", response_class=HTMLResponse)
    async def web_form_create(
        module: str, name: str, request: Request,
        env: Environment = Depends(get_env),
    ):
        from .render import parse_form_vals, render_form_page

        view = _require_form_view(_load_view(env, module, name))
        form = await request.form()
        cls = env.registry[view.model]
        vals = parse_form_vals(cls, form)
        with env.transaction():
            rec = env[view.model].create(vals)
        body_only = request.headers.get("HX-Request") == "true"
        return HTMLResponse(
            render_form_page(view, rec, env, mode="display", body_only=body_only)
        )

    return app
