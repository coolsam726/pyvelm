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

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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
            raise HTTPException(
                status_code=501,
                detail=f"Renderer for view_type {rec.view_type!r} not yet shipped",
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

    return app
