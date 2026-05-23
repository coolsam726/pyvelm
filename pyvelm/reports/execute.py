"""Execute compiled reports with ACL + record rules."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .compile import ColumnMeta, compile_report, parse_definition
from .format import normalize_column_format
from .schema import validate_definition


@dataclass
class ReportResult:
    columns: list[ColumnMeta]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: int
    truncated: bool = False
    is_aggregate: bool = False


def _secured_definition(defn: dict, env) -> dict:
    """Return a copy of *defn* with record rules and company scope in filters."""
    root = defn["root"]
    env.check_access(root, "read")
    root_cls = env.registry[root]
    secured = dict(defn)
    filters = list(defn.get("filters") or [])
    rule_leaves = env.collect_record_rules(root, "read")
    if rule_leaves:
        filters.extend(rule_leaves)
    if (
        not env._acl_bypass
        and env.company_id is not None
        and getattr(root_cls, "_company_scoped", False)
    ):
        filters.append(("company_id", "=", env.company_id))
    secured["filters"] = filters
    return secured


def _resolve_m2o_labels(env, columns: list[ColumnMeta], rows: list[dict]) -> None:
    for col in columns:
        if not col.is_m2o or not col.comodel:
            continue
        ids = {r[col.key] for r in rows if r.get(col.key) is not None}
        if not ids:
            continue
        labels: dict[int, str] = {}
        CoModel = env[col.comodel]
        for rec in CoModel.browse(tuple(ids)):
            for attr in ("display_name", "name"):
                if attr in rec._fields:
                    labels[rec.id] = str(getattr(rec, attr) or rec.id)
                    break
            else:
                labels[rec.id] = str(rec.id)
        label_key = f"{col.key}__label"
        for r in rows:
            rid = r.get(col.key)
            r[label_key] = labels.get(rid) if rid is not None else None


def _resolve_currency_symbols(env, columns: list[ColumnMeta], rows: list[dict]) -> None:
    """Attach per-row ``{col.key}__currency_symbol`` for currency-formatted columns."""
    if "res.currency" not in env.registry:
        return
    try:
        env.check_access("res.currency", "read")
    except PermissionError:
        return
    Currency = env["res.currency"]
    sym_key = "__currency_symbol"

    for col in columns:
        fmt = col.format_dict()
        if fmt.get("type") != "currency":
            continue
        out_key = f"{col.key}{sym_key}"
        src = fmt.get("currency_source", "field")

        if src == "fixed" or fmt.get("currency_id"):
            cid = fmt.get("currency_id")
            symbol = ""
            if cid:
                rec = Currency.browse((int(cid),))
                if rec.id:
                    symbol = str(rec.symbol or rec.code or "")
            for r in rows:
                r[out_key] = symbol
            continue

        id_key = col.currency_id_key or f"{col.key}__currency_id"
        ids = {r[id_key] for r in rows if r.get(id_key) is not None}
        if not ids:
            continue
        symbols: dict[int, str] = {}
        for rec in Currency.browse(tuple(ids)):
            symbols[rec.id] = str(rec.symbol or rec.code or "")
        for r in rows:
            cid = r.get(id_key)
            r[out_key] = symbols.get(cid, "") if cid is not None else ""


def run_report(
    env,
    definition: str | dict,
    params: dict[str, Any] | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> ReportResult:
    """Run a report definition under the current user's security context."""
    defn = parse_definition(definition)
    validate_definition(defn, env.registry)
    from .fields_api import check_definition_access
    check_definition_access(env, defn)
    secured = _secured_definition(defn, env)

    t0 = time.perf_counter()
    compiled = compile_report(secured, env.registry, params, limit=limit, offset=offset)
    cur = env.conn.execute(compiled.sql, compiled.params)
    raw_rows = cur.fetchall()
    duration_ms = int((time.perf_counter() - t0) * 1000)

    rows: list[dict[str, Any]] = []
    if compiled.row_key_order:
        for raw in raw_rows:
            d: dict[str, Any] = {}
            ccy_pending: dict[str, Any] = {}
            for j, (kind, key) in enumerate(compiled.row_key_order):
                val = raw[j]
                if kind == "data":
                    d[key] = val
                else:
                    ccy_pending[key] = val
            for key, cid in ccy_pending.items():
                d[f"{key}__currency_id"] = cid
            rows.append(d)
    else:
        for raw in raw_rows:
            d: dict[str, Any] = {}
            for i, col in enumerate(compiled.columns):
                d[col.key] = raw[i]
            rows.append(d)
    _resolve_m2o_labels(env, compiled.columns, rows)
    _resolve_currency_symbols(env, compiled.columns, rows)

    truncated = limit is not None and len(rows) >= limit
    return ReportResult(
        columns=compiled.columns,
        rows=rows,
        row_count=len(rows),
        duration_ms=duration_ms,
        truncated=truncated,
        is_aggregate=compiled.is_aggregate,
    )
