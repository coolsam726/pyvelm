"""Shared report run helpers for web/API layers."""
from __future__ import annotations

from typing import Any

from .compile import parse_definition
from .execute import ReportResult, run_report
from .schema import ReportDefinitionError, validate_definition

PREVIEW_LIMIT = 100


def load_report(env, report_id: int):
    Report = env["ir.report"]
    recs = Report.search([("id", "=", report_id), ("active", "=", True)], limit=1)
    if not recs:
        return None
    recs.ensure_one()
    return recs


def can_run_report(env, report_rec) -> bool:
    """True when the user may execute *report_rec*."""
    env.check_access("ir.report", "read")
    if env.uid == 1:
        return True
    allowed = report_rec.group_ids
    if not allowed:
        return True
    user = env["res.users"].browse((env.uid,))
    user.ensure_one()
    allowed_ids = set(allowed.ids)
    for gid in user.group_ids.ids:
        if gid in allowed_ids:
            return True
    return False


def definition_dict(report_rec) -> dict[str, Any]:
    return parse_definition(report_rec.definition)


def parse_run_params(defn: dict, query: dict[str, str]) -> dict[str, Any]:
    """Extract runtime parameter values from query string keys."""
    out: dict[str, Any] = {}
    for spec in defn.get("parameters") or []:
        name = spec["name"]
        if name not in query:
            continue
        raw = query[name]
        ptype = spec.get("type", "string")
        if ptype == "boolean":
            out[name] = raw.lower() in ("1", "true", "yes", "on")
        elif ptype == "integer":
            out[name] = int(raw)
        elif ptype == "float":
            out[name] = float(raw)
        else:
            out[name] = raw
    return out


def execute_report(
    env,
    report_rec,
    params: dict[str, Any] | None = None,
    *,
    limit: int | None = None,
) -> ReportResult:
    defn = definition_dict(report_rec)
    validate_definition(defn, env.registry)
    if defn["root"] != report_rec.root_model:
        raise ReportDefinitionError(
            f"definition.root {defn['root']!r} != root_model {report_rec.root_model!r}"
        )
    row_limit = int(report_rec.row_limit or 10000)
    if limit is None:
        limit = row_limit
    else:
        limit = min(limit, row_limit)
    return run_report(env, defn, params, limit=limit)


def log_run(
    env,
    report_rec,
    *,
    row_count: int,
    duration_ms: int,
    fmt: str,
    state: str = "done",
    error_message: str | None = None,
) -> None:
    if "ir.report.run" not in env.registry:
        return
    Run = env["ir.report.run"]
    user = env["res.users"].browse((env.uid,)) if env.uid else None
    Run.create({
        "report_id": report_rec,
        "user_id": user if user and user.id else None,
        "row_count": row_count,
        "duration_ms": duration_ms,
        "format": fmt,
        "state": state,
        "error_message": error_message,
    })


def result_to_json(result: ReportResult) -> dict[str, Any]:
    return {
        "columns": [
            {
                "key": c.key,
                "label": c.label,
                "expr": c.expr,
                "format": c.format_dict(),
            }
            for c in result.columns
        ],
        "rows": result.rows,
        "row_count": result.row_count,
        "duration_ms": result.duration_ms,
        "truncated": result.truncated,
    }
