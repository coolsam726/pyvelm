"""Report definition → parameterized SQL (schema v1)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain import domain_to_sql
from ..fields import Date, Datetime, Float, Integer, Many2one
from ..paths import M2oHop, parse_path
from .compile_collections import column_sql_for_path
from .fields_api import monetary_currency_path
from .format import normalize_column_format
from .schema import validate_definition


@dataclass
class ColumnMeta:
    key: str
    label: str
    expr: str
    is_m2o: bool = False
    comodel: str | None = None
    format: dict | None = None
    currency_id_key: str | None = None

    def format_dict(self) -> dict:
        return normalize_column_format(self.format)


@dataclass
class CompiledReport:
    sql: str
    params: list[Any]
    columns: list[ColumnMeta]
    is_aggregate: bool = False
    row_key_order: list[tuple[str, str]] | None = None


def _column_sql(
    expr: str,
    root_cls,
    registry,
    base_alias: str,
    joins: list[str],
    join_aliases: dict[tuple, str],
    join_counter: list[int],
    subaggregate: str | None = None,
) -> tuple[str, bool, str | None]:
    return column_sql_for_path(
        expr, root_cls, base_alias, registry,
        joins, join_aliases, join_counter, subaggregate,
    )


def _merge_domain(defn: dict, params: dict[str, Any]) -> list:
    domain: list = list(defn.get("filters") or [])
    for leaf in defn.get("parameter_filters") or []:
        domain.append(_substitute_param_leaf(leaf, params))
    return domain


def _substitute_param_leaf(leaf, params: dict[str, Any]):
    if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "__or__":
        op = leaf[1]
        subs = [_substitute_param_leaf(s, params) for s in (leaf[2] or [])]
        subs = [s for s in subs if s is not None]
        if not subs:
            return None
        return ("__or__", op, subs)
    attr, op, value = leaf[0], leaf[1], leaf[2]
    opts = leaf[3] if len(leaf) == 4 else None
    if isinstance(value, dict) and "param" in value:
        pname = value["param"]
        pval = params.get(pname)
        if pval is None or pval == "":
            # Skip optional empty parameter filters at execution time.
            return None
        value = pval
    if opts is not None:
        return (attr, op, value, opts)
    return (attr, op, value)


def _compact_domain(domain: list) -> list:
    out: list = []
    for leaf in domain:
        if leaf is None:
            continue
        if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "__or__":
            subs = _compact_domain(list(leaf[2] or []))
            if subs:
                out.append(("__or__", leaf[1], subs))
            continue
        out.append(leaf)
    return out


def compile_report(
    defn: dict[str, Any],
    registry,
    params: dict[str, Any] | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> CompiledReport:
    """Compile a validated definition to SQL."""
    validate_definition(defn, registry)
    params = params or {}
    root = defn["root"]
    root_cls = registry[root]
    base_alias = f'"{root_cls._table}"'
    joins: list[str] = []
    join_aliases: dict[tuple, str] = {}
    join_counter = [0]

    groupby = list(defn.get("groupby") or [])
    measures = list(defn.get("measures") or [])
    is_aggregate = bool(groupby and measures)

    columns_meta: list[ColumnMeta] = []
    select_parts: list[str] = []
    group_sql_parts: list[str] = []
    row_key_order: list[tuple[str, str]] | None = None

    if is_aggregate:
        _VALID_TRUNCS = ("day", "week", "month", "quarter", "year")
        _VALID_AGGS = ("sum", "avg", "min", "max", "count")
        group_keys: list[tuple[str, str, str | None, bool, str | None]] = []

        for spec in groupby:
            if ":" in spec:
                fname, trunc = spec.split(":", 1)
            else:
                fname, trunc = spec, None
            field = root_cls._fields[fname]
            col_sql = f'{base_alias}."{field.column}"'
            if trunc:
                if trunc not in _VALID_TRUNCS:
                    raise ValueError(f"Bad trunc {trunc!r}")
                expr = f"date_trunc('{trunc}', {col_sql})"
            else:
                expr = col_sql
            alias = f"g_{len(group_keys)}"
            select_parts.append(f'{expr} AS "{alias}"')
            group_sql_parts.append(expr)
            is_m2o = isinstance(field, Many2one)
            comodel = field.comodel_name if is_m2o else None
            group_keys.append((spec, fname, trunc, is_m2o, comodel))
            columns_meta.append(
                ColumnMeta(key=spec, label=spec, expr=spec, is_m2o=is_m2o, comodel=comodel)
            )

        measure_keys: list[tuple[str, str, str | None]] = []
        for spec in measures:
            if spec == "__count":
                select_parts.append('COUNT(*) AS "__count"')
                measure_keys.append(("__count", "count", None))
                columns_meta.append(
                    ColumnMeta(key="__count", label="Count", expr="__count")
                )
                continue
            if ":" in spec:
                mfield, agg = spec.split(":", 1)
            else:
                mfield, agg = spec, "sum"
            if agg not in _VALID_AGGS:
                raise ValueError(f"Bad aggregate {agg!r}")
            mf = root_cls._fields[mfield]
            alias = f"m_{len(measure_keys)}"
            col = f'{base_alias}."{mf.column}"'
            select_parts.append(f'{agg.upper()}({col}) AS "{alias}"')
            measure_keys.append((spec, agg, mfield))
            columns_meta.append(
                ColumnMeta(key=spec, label=spec, expr=spec)
            )
    else:
        row_key_order: list[tuple[str, str]] = []
        for i, col in enumerate(defn["columns"]):
            expr = col["expr"]
            subagg = col.get("subaggregate")
            sql_expr, is_m2o, comodel = _column_sql(
                expr, root_cls, registry, base_alias, joins, join_aliases, join_counter,
                subagg,
            )
            alias = f"c_{i}"
            select_parts.append(f'{sql_expr} AS "{alias}"')
            row_key_order.append(("data", expr))

            currency_id_key = None
            fmt = normalize_column_format(col.get("format"))
            if fmt.get("type") == "currency":
                src = fmt.get("currency_source", "field")
                if src == "field" and fmt.get("currency_field"):
                    ccy_path = monetary_currency_path(expr, fmt["currency_field"])
                    try:
                        ccy_sql, _, _ = _column_sql(
                            ccy_path, root_cls, registry, base_alias, joins,
                            join_aliases, join_counter, None,
                        )
                        ccy_alias = f"__ccy_{i}"
                        select_parts.append(f'{ccy_sql} AS "{ccy_alias}"')
                        currency_id_key = f"{expr}__currency_id"
                        row_key_order.append(("ccy", expr))
                    except (ValueError, KeyError):
                        currency_id_key = None

            columns_meta.append(
                ColumnMeta(
                    key=expr,
                    label=col["label"],
                    expr=expr,
                    is_m2o=is_m2o,
                    comodel=comodel,
                    format=col.get("format"),
                    currency_id_key=currency_id_key,
                )
            )

    domain = _compact_domain(_merge_domain(defn, params))
    where, bind_params, domain_joins = domain_to_sql(domain, root_cls, registry)

    order_specs = list(defn.get("order") or [])
    order_sql_cache: dict[str, str] = {}
    if not is_aggregate and order_specs:
        column_exprs = {col["expr"] for col in defn["columns"]}
        for item in order_specs:
            fname, _direction = item.rsplit(None, 1)
            if fname in column_exprs:
                continue
            try:
                sql, _, _ = _column_sql(
                    fname, root_cls, registry, base_alias, joins, join_aliases, join_counter,
                    None,
                )
                order_sql_cache[fname] = sql
            except (ValueError, KeyError):
                continue

    extra_joins = " ".join(joins)
    join_sql = f"{domain_joins} {extra_joins}".strip()
    join_clause = f" {join_sql}" if join_sql else ""

    sql = f'SELECT {", ".join(select_parts)} FROM {base_alias}{join_clause} WHERE {where}'
    if group_sql_parts:
        sql += " GROUP BY " + ", ".join(group_sql_parts)

    order_parts: list[str] = []
    if is_aggregate:
        key_to_alias = {m.key: f'"{m.key}"' for m in columns_meta}
        for item in order_specs:
            fname, direction = item.rsplit(None, 1)
            direction = direction.upper()
            if fname in key_to_alias:
                order_parts.append(f'{key_to_alias[fname]} {direction}')
    else:
        expr_to_alias = {m.expr: f'"c_{i}"' for i, m in enumerate(columns_meta)}
        for item in order_specs:
            fname, direction = item.rsplit(None, 1)
            direction = direction.upper()
            if fname in expr_to_alias:
                order_parts.append(f'{expr_to_alias[fname]} {direction}')
            elif fname in order_sql_cache:
                order_parts.append(f'{order_sql_cache[fname]} {direction}')
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)

    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    if offset:
        sql += f" OFFSET {int(offset)}"

    return CompiledReport(
        sql=sql,
        params=bind_params,
        columns=columns_meta,
        is_aggregate=is_aggregate,
        row_key_order=row_key_order,
    )


def parse_definition(raw: str | dict | None) -> dict[str, Any]:
    if raw is None or raw == "":
        raise ValueError("Report definition is empty")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    raise ValueError(f"Invalid definition type: {type(raw).__name__}")
