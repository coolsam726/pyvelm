"""Report definition → parameterized SQL (schema v1)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..fields import Many2one
from .compile_collections import column_expr_for_path
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
    stmt: Any = None


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
    capabilities=None,
) -> CompiledReport:
    """Compile a validated definition to SQL."""
    validate_definition(defn, registry)
    params = params or {}
    root = defn["root"]
    root_cls = registry[root]
    base_alias = f'"{root_cls._table}"'
    join_aliases: dict[tuple, str] = {}
    join_counter = [0]

    groupby = list(defn.get("groupby") or [])
    measures = list(defn.get("measures") or [])
    is_aggregate = bool(groupby and measures)

    from sqlalchemy import func, select
    from sqlalchemy.sql.expression import literal_column, text as sa_text

    from ..database.dialects import dialect_capabilities
    from ..domain_sa import (
        DomainCompiler,
        apply_search_pagination,
        column_element_to_sql,
        statement_to_driver_sql,
    )

    cap = capabilities if capabilities is not None else dialect_capabilities("postgresql")
    compiler = DomainCompiler(
        root_cls,
        registry,
        cap,
        join_aliases=join_aliases,
        join_counter=join_counter,
    )

    columns_meta: list[ColumnMeta] = []
    select_cols: list = []
    group_by_cols: list = []
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
            col_expr = literal_column(f'"{root_cls._table}"."{field.column}"')
            if trunc:
                if trunc not in _VALID_TRUNCS:
                    raise ValueError(f"Bad trunc {trunc!r}")
                if cap.name == "postgresql":
                    expr = func.date_trunc(trunc, col_expr)
                else:
                    expr = literal_column(
                        f"date_trunc('{trunc}', \"{root_cls._table}\"."
                        f'"{field.column}")'
                    )
            else:
                expr = col_expr
            alias = f"g_{len(group_keys)}"
            select_cols.append(expr.label(alias))
            group_by_cols.append(expr)
            is_m2o = isinstance(field, Many2one)
            comodel = field.comodel_name if is_m2o else None
            group_keys.append((spec, fname, trunc, is_m2o, comodel))
            columns_meta.append(
                ColumnMeta(key=spec, label=spec, expr=spec, is_m2o=is_m2o, comodel=comodel)
            )

        for spec in measures:
            if spec == "__count":
                select_cols.append(func.count().label("__count"))
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
            alias = f"m_{len(columns_meta)}"
            col_expr = literal_column(f'"{root_cls._table}"."{mf.column}"')
            select_cols.append(getattr(func, agg)(col_expr).label(alias))
            columns_meta.append(
                ColumnMeta(key=spec, label=spec, expr=spec)
            )
    else:
        row_key_order = []
        for i, col in enumerate(defn["columns"]):
            expr = col["expr"]
            subagg = col.get("subaggregate")
            col_expr, is_m2o, comodel = column_expr_for_path(
                expr,
                root_cls,
                base_alias,
                registry,
                [],
                join_aliases,
                join_counter,
                subagg,
                compiler=compiler,
            )
            alias = f"c_{i}"
            select_cols.append(col_expr.label(alias))
            row_key_order.append(("data", expr))

            currency_id_key = None
            fmt = normalize_column_format(col.get("format"))
            if fmt.get("type") == "currency":
                src = fmt.get("currency_source", "field")
                if src == "field" and fmt.get("currency_field"):
                    ccy_path = monetary_currency_path(expr, fmt["currency_field"])
                    try:
                        ccy_expr, _, _ = column_expr_for_path(
                            ccy_path,
                            root_cls,
                            base_alias,
                            registry,
                            [],
                            join_aliases,
                            join_counter,
                            None,
                            compiler=compiler,
                        )
                        select_cols.append(ccy_expr.label(f"__ccy_{i}"))
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
    where = compiler.compile_where(domain)
    stmt = select(*select_cols).select_from(compiler.from_clause()).where(where)
    if group_by_cols:
        stmt = stmt.group_by(*group_by_cols)

    order_specs = list(defn.get("order") or [])
    order_sql_cache: dict[str, str] = {}
    if not is_aggregate and order_specs:
        column_exprs = {col["expr"] for col in defn["columns"]}
        for item in order_specs:
            fname, _direction = item.rsplit(None, 1)
            if fname in column_exprs:
                continue
            try:
                order_expr, _, _ = column_expr_for_path(
                    fname,
                    root_cls,
                    base_alias,
                    registry,
                    [],
                    join_aliases,
                    join_counter,
                    None,
                    compiler=compiler,
                )
                order_sql_cache[fname] = column_element_to_sql(order_expr, cap)
            except (ValueError, KeyError):
                continue

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
        stmt = stmt.order_by(sa_text(", ".join(order_parts)))

    stmt = apply_search_pagination(
        stmt,
        cap,
        base_table=root_cls._table,
        limit=limit,
        offset=offset,
        has_order=bool(order_parts),
    )
    sql, bind_params = statement_to_driver_sql(stmt, cap)

    return CompiledReport(
        sql=sql,
        params=bind_params,
        columns=columns_meta,
        is_aggregate=is_aggregate,
        row_key_order=row_key_order,
        stmt=stmt,
    )


def parse_definition(raw: str | dict | None) -> dict[str, Any]:
    if raw is None or raw == "":
        raise ValueError("Report definition is empty")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    raise ValueError(f"Invalid definition type: {type(raw).__name__}")
