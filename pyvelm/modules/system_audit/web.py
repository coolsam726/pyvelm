"""CSV export routes for audit tables."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from pyvelm import Environment
from pyvelm.request_env import SESSION_COOKIE, apply_request_scope


def _stream_csv(filename: str, headers: list[str], rows: list[list[Any]]):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _cell(value: Any) -> Any:
    if value is None or value is False:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    if hasattr(value, "_ids"):
        return value._ids[0] if len(value._ids) == 1 else list(value._ids)
    if hasattr(value, "id"):
        return value.id
    return value


def register_routes(app) -> None:
    registry = app.state.registry
    pool = app.state.pool

    def _resolve_session(env, token):
        from pyvelm.session_auth import resolve_session_uid

        return resolve_session_uid(env, token)

    def get_env(request: Request):
        with pool.connection() as conn:
            env = Environment(conn, registry=registry, uid=None)
            env = apply_request_scope(
                env, request, resolve_session=_resolve_session, resolve_basic=lambda _e, _a: None
            )
            if env.uid is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            yield env

    def _export(
        env: Environment,
        model_name: str,
        filename: str,
        columns: list[str],
    ):
        if model_name not in env.registry:
            raise HTTPException(status_code=404, detail="Audit module is not installed.")
        try:
            env.check_access(model_name, "read")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        records = env[model_name].search([], order="id desc")
        rows = []
        for rec in records:
            rows.append([_cell(getattr(rec, col, None)) for col in columns])
        return _stream_csv(filename, columns, rows)

    @app.get("/web/audit/logs/export")
    def export_audit_logs(env: Environment = Depends(get_env)):
        return _export(
            env,
            "ir.audit.log",
            "audit-log.csv",
            [
                "created_at",
                "name",
                "model",
                "res_id",
                "action",
                "user_id",
                "company_id",
                "ip_address",
                "user_agent",
            ],
        )

    @app.get("/web/audit/logins/export")
    def export_login_logs(env: Environment = Depends(get_env)):
        return _export(
            env,
            "ir.login.log",
            "login-history.csv",
            [
                "created_at",
                "event",
                "user_id",
                "email",
                "ip_address",
                "user_agent",
                "session_id",
                "session_lifetime_minutes",
            ],
        )

    @app.get("/web/audit/lifecycle/export")
    def export_user_lifecycle(env: Environment = Depends(get_env)):
        return _export(
            env,
            "ir.user.lifecycle",
            "user-lifecycle.csv",
            [
                "created_at",
                "event",
                "user_id",
                "actor_id",
                "detail",
            ],
        )
