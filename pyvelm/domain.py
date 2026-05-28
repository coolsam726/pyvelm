"""Domain → SQL compiler.

A domain is `[(attr, op, value), ...]`, implicitly AND-ed. Attrs may be
dotted (`country_id.code`, `tag_ids.name`); the path is parsed against the
model. Pure Many2one chains compile to memoized `LEFT JOIN`s. Paths with at
least one One2many or Many2many hop compile to per-leaf `EXISTS` subqueries
(existential semantics on collections).

Public surface:
    domain_to_sql(domain, model_cls) -> (where, params, joins)

`where` is the SQL after `WHERE` (defaults to `TRUE`).
`joins` is the `LEFT JOIN ...` text to splice between the base table and
`WHERE` (empty when no traversal is used).
`params` are the bind values, in order.

Operators: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `like`, `ilike`.
Empty `in`/`not in` short-circuit to `FALSE`/`TRUE`.

Collection paths (O2m/M2m) accept an optional fourth element — a dict with
``{"all": True}`` — for universal quantification: every member must satisfy
the condition (implemented as ``NOT EXISTS`` over members that fail it).
"""
from __future__ import annotations

from typing import Any, Iterable

from .paths import M2mHop, M2oHop, O2mHop, parse_path

_SIMPLE_OPS = {"=", "!=", "<", "<=", ">", ">="}
# For {"all": True} on collection paths: emit NOT EXISTS(member fails op).
_ALL_FAIL_OPS = {
    "=": "!=",
    "!=": "=",
    "<": ">=",
    "<=": ">",
    ">": "<=",
    ">=": "<",
    "in": "not in",
    "not in": "in",
}


def _parse_leaf(leaf) -> tuple[str, str, Any, bool]:
    """Return (attr, op, value, universal)."""
    if not isinstance(leaf, (list, tuple)) or len(leaf) not in (3, 4):
        raise ValueError(f"Invalid domain leaf: {leaf!r}")
    attr, op, value = leaf[0], leaf[1], leaf[2]
    universal = False
    if len(leaf) == 4:
        opts = leaf[3]
        if not isinstance(opts, dict):
            raise ValueError(
                f"Domain leaf 4th element must be a dict, got {type(opts).__name__}"
            )
        universal = bool(opts.get("all"))
    return attr, op, value, universal


def _resolve_simple(model_cls, attr: str):
    """Single-token attr resolution. Returns (column, field_or_None)."""
    if attr == "id":
        return "id", None
    if attr not in model_cls._fields:
        raise ValueError(
            f"Unknown field {attr!r} on {model_cls._name} in domain"
        )
    field = model_cls._fields[attr]
    return field.column, field


def _coerce(field, value):
    if field is None:
        return value
    return field.to_sql_param(value)


def domain_to_sql(
    domain: Iterable[tuple[str, str, Any]] | None,
    model_cls,
    registry,
    *,
    joins: list[str] | None = None,
    join_aliases: dict[tuple, str] | None = None,
    join_counter: list[int] | None = None,
) -> tuple[str, list[Any], str]:
    """Compile a domain to SQL.

    When ``joins`` / ``join_aliases`` / ``join_counter`` are passed, JOIN
    emission appends to those shared structures (used by the report compiler
    so column and filter paths reuse the same ``_jN`` aliases). In that
    mode the third return value is always ``""`` — read ``joins`` instead.
    """
    if not domain:
        return "TRUE", [], ""

    base_alias = f'"{model_cls._table}"'
    clauses: list[str] = []
    params: list[Any] = []
    shared_joins = joins is not None
    if joins is None:
        joins = []
    if join_aliases is None:
        join_aliases = {}
    if join_counter is None:
        join_counter = [0]

    def _emit_chain(hops) -> str:
        """Emit LEFT JOINs for a Many2one chain; return the alias of the
        final joined table (the one carrying the leaf attr)."""
        key: tuple = (base_alias,)
        current_alias = base_alias
        for hop in hops:
            if not isinstance(hop, M2oHop):
                raise NotImplementedError(
                    f"Domain traversal through "
                    f"{type(hop).__name__}.{hop.attr} not supported yet "
                    f"(use the inverse side or wait for EXISTS-style "
                    f"subqueries)"
                )
            key = key + (hop.attr,)
            if key in join_aliases:
                current_alias = join_aliases[key]
                continue
            join_counter[0] += 1
            new_alias = f"_j{join_counter[0]}"
            target = registry[hop.target_model]
            joins.append(
                f'LEFT JOIN "{target._table}" {new_alias} ON '
                f'{new_alias}."id" = {current_alias}."{hop.field.column}"'
            )
            join_aliases[key] = new_alias
            current_alias = new_alias
        return current_alias

    def _resolve_leaf_field(path):
        leaf_cls = registry[path.leaf_model]
        if path.leaf_attr == "id":
            return None
        leaf_field = leaf_cls._fields.get(path.leaf_attr)
        if leaf_field is None:
            raise ValueError(
                f"Path on {model_cls._name}: {path.leaf_model} has no field "
                f"{path.leaf_attr!r}"
            )
        return leaf_field

    def _emit_exists(path, op: str, value, *, universal: bool = False):
        """Emit `EXISTS (...)` for a path containing at least one O2m/M2m
        hop. Each call generates a fresh subquery — consecutive collection
        leaves can match different members, which is the intuitive read.

        With ``universal=True``, emit ``NOT EXISTS`` over members that
        *fail* the condition (every member must satisfy ``op``/``value``).
        """
        if universal and op not in _ALL_FAIL_OPS and op not in ("like", "ilike"):
            raise ValueError(
                f"Operator {op!r} does not support {{'all': True}} on collection paths"
            )
        leaf_op = op
        if universal and op in _ALL_FAIL_OPS:
            leaf_op = _ALL_FAIL_OPS[op]
        join_counter[0] += 1
        suffix = join_counter[0]
        froms: list[str] = []
        inner_clauses: list[str] = []
        inner_params: list[Any] = []
        prev_alias: str | None = None
        prev_is_id_side: bool = False  # whether prev_alias.id is the "row id"

        for i, hop in enumerate(path.hops):
            if isinstance(hop, O2mHop):
                tgt = registry[hop.target_model]
                inverse_col = tgt._fields[hop.inverse_attr].column
                alias = f"_e{suffix}_{i}"
                if i == 0:
                    froms.append(f'"{tgt._table}" {alias}')
                    inner_clauses.append(
                        f'{alias}."{inverse_col}" = {base_alias}."id"'
                    )
                else:
                    assert prev_alias is not None
                    froms.append(
                        f'JOIN "{tgt._table}" {alias} ON '
                        f'{alias}."{inverse_col}" = {prev_alias}."id"'
                    )
                prev_alias = alias
                prev_is_id_side = True
            elif isinstance(hop, M2mHop):
                j_alias = f"_e{suffix}_{i}j"
                t_alias = f"_e{suffix}_{i}t"
                tgt = registry[hop.target_model]
                if i == 0:
                    froms.append(f'"{hop.relation}" {j_alias}')
                    inner_clauses.append(
                        f'{j_alias}."{hop.col1}" = {base_alias}."id"'
                    )
                else:
                    assert prev_alias is not None
                    froms.append(
                        f'JOIN "{hop.relation}" {j_alias} ON '
                        f'{j_alias}."{hop.col1}" = {prev_alias}."id"'
                    )
                froms.append(
                    f'JOIN "{tgt._table}" {t_alias} ON '
                    f'{t_alias}."id" = {j_alias}."{hop.col2}"'
                )
                prev_alias = t_alias
                prev_is_id_side = True
            elif isinstance(hop, M2oHop):
                tgt = registry[hop.target_model]
                alias = f"_e{suffix}_{i}"
                if i == 0:
                    # Forward M2o without a prior collection step would
                    # normally use LEFT JOIN; if we got here, EXISTS was
                    # forced by a later collection hop. Anchor by the FK
                    # column on the outer base.
                    froms.append(f'"{tgt._table}" {alias}')
                    inner_clauses.append(
                        f'{alias}."id" = {base_alias}."{hop.field.column}"'
                    )
                else:
                    assert prev_alias is not None
                    froms.append(
                        f'LEFT JOIN "{tgt._table}" {alias} ON '
                        f'{alias}."id" = {prev_alias}."{hop.field.column}"'
                    )
                prev_alias = alias
                prev_is_id_side = True

        assert prev_alias is not None
        leaf_field = _resolve_leaf_field(path)
        leaf_col = leaf_field.column if leaf_field is not None else "id"
        leaf_ref = f'{prev_alias}."{leaf_col}"'

        # Build the leaf condition using the same operator dispatch as the
        # outer compiler, but writing directly into inner_clauses/params.
        if leaf_op in _SIMPLE_OPS:
            v = _coerce(leaf_field, value)
            if v is None and leaf_op == "=":
                inner_clauses.append(f"{leaf_ref} IS NULL")
            elif v is None and leaf_op == "!=":
                inner_clauses.append(f"{leaf_ref} IS NOT NULL")
            else:
                inner_clauses.append(f"{leaf_ref} {leaf_op} %s")
                inner_params.append(v)
        elif leaf_op == "in":
            values = [_coerce(leaf_field, v) for v in value]
            if not values:
                return ("TRUE", []) if universal else ("FALSE", [])
            placeholders = ",".join(["%s"] * len(values))
            inner_clauses.append(f"{leaf_ref} IN ({placeholders})")
            inner_params.extend(values)
        elif leaf_op == "not in":
            values = [_coerce(leaf_field, v) for v in value]
            if not values:
                return ("TRUE", []) if universal else ("TRUE", [])
            placeholders = ",".join(["%s"] * len(values))
            inner_clauses.append(f"{leaf_ref} NOT IN ({placeholders})")
            inner_params.extend(values)
        elif universal and op == "like":
            inner_clauses.append(f"{leaf_ref} NOT LIKE %s")
            inner_params.append(value)
        elif universal and op == "ilike":
            inner_clauses.append(f"{leaf_ref} NOT ILIKE %s")
            inner_params.append(value)
        elif leaf_op == "like":
            inner_clauses.append(f"{leaf_ref} LIKE %s")
            inner_params.append(value)
        elif leaf_op == "ilike":
            inner_clauses.append(f"{leaf_ref} ILIKE %s")
            inner_params.append(value)
        else:
            raise ValueError(f"Unknown operator: {leaf_op!r}")

        sql_body = " ".join(froms)
        exists_sql = (
            f"EXISTS (SELECT 1 FROM {sql_body} "
            f'WHERE {" AND ".join(inner_clauses)})'
        )
        if universal:
            return f"NOT ({exists_sql})", inner_params
        return exists_sql, inner_params

    def _leaf_ref(attr: str):
        """Return (qualified_column_sql, field_or_None) for `attr`. Parses
        paths and emits joins as a side effect."""
        if "." not in attr:
            col, field = _resolve_simple(model_cls, attr)
            return f'{base_alias}."{col}"', field
        # Path attr: parse, emit joins, qualify the leaf column.
        path = parse_path(model_cls, attr, registry)
        leaf_alias = _emit_chain(path.hops)
        leaf_cls = registry[path.leaf_model]
        if path.leaf_attr == "id":
            return f'{leaf_alias}."id"', None
        leaf_field = leaf_cls._fields.get(path.leaf_attr)
        if leaf_field is None:
            raise ValueError(
                f"Path {attr!r}: {path.leaf_model} has no field "
                f"{path.leaf_attr!r}"
            )
        return f'{leaf_alias}."{leaf_field.column}"', leaf_field

    for leaf in domain:
        attr, op, value, universal = _parse_leaf(leaf)

        # Special __or__ operator: value is a list of (attr, op, val) leaves
        # that should be OR-ed together. Useful for multi-field text search.
        if attr == "__or__":
            sub_clauses: list[str] = []
            for sub_leaf in value or []:
                s_attr, s_op, s_val, s_all = _parse_leaf(sub_leaf)
                if s_all and "." not in s_attr:
                    raise ValueError(
                        f"{{'all': True}} only applies to collection paths, got {s_attr!r}"
                    )
                if "." in s_attr:
                    path = parse_path(model_cls, s_attr, registry)
                    if not path.is_m2o_only():
                        s_clause, s_ps = _emit_exists(
                            path, s_op, s_val, universal=s_all
                        )
                        sub_clauses.append(s_clause)
                        params.extend(s_ps)
                        continue
                s_col, s_field = _leaf_ref(s_attr)
                if s_op == "ilike":
                    sub_clauses.append(f"{s_col} ILIKE %s")
                    params.append(s_val)
                elif s_op == "like":
                    sub_clauses.append(f"{s_col} LIKE %s")
                    params.append(s_val)
                elif s_op in _SIMPLE_OPS:
                    v = _coerce(s_field, s_val)
                    if v is None and s_op == "=":
                        sub_clauses.append(f"{s_col} IS NULL")
                    elif v is None and s_op == "!=":
                        sub_clauses.append(f"{s_col} IS NOT NULL")
                    else:
                        sub_clauses.append(f"{s_col} {s_op} %s")
                        params.append(v)
            if sub_clauses:
                clauses.append("(" + " OR ".join(sub_clauses) + ")")
            continue

        # Paths containing any O2m/M2m hop go through an EXISTS subquery.
        # Pure-M2o paths stay in the LEFT JOIN path so multiple leaves
        # on the same chain share a single join.
        if universal and "." not in attr:
            raise ValueError(
                f"{{'all': True}} only applies to collection paths, got {attr!r}"
            )
        if "." in attr:
            path = parse_path(model_cls, attr, registry)
            if not path.is_m2o_only():
                clause, ps = _emit_exists(path, op, value, universal=universal)
                clauses.append(clause)
                params.extend(ps)
                continue

        col_sql, field = _leaf_ref(attr)


        if op in _SIMPLE_OPS:
            v = _coerce(field, value)
            if v is None and op == "=":
                clauses.append(f"{col_sql} IS NULL")
            elif v is None and op == "!=":
                clauses.append(f"{col_sql} IS NOT NULL")
            else:
                clauses.append(f"{col_sql} {op} %s")
                params.append(v)
        elif op == "in":
            values = [_coerce(field, v) for v in value]
            if not values:
                clauses.append("FALSE")
            else:
                placeholders = ",".join(["%s"] * len(values))
                clauses.append(f"{col_sql} IN ({placeholders})")
                params.extend(values)
        elif op == "not in":
            values = [_coerce(field, v) for v in value]
            if not values:
                clauses.append("TRUE")
            else:
                placeholders = ",".join(["%s"] * len(values))
                clauses.append(f"{col_sql} NOT IN ({placeholders})")
                params.extend(values)
        elif op == "like":
            clauses.append(f"{col_sql} LIKE %s")
            params.append(value)
        elif op == "ilike":
            clauses.append(f"{col_sql} ILIKE %s")
            params.append(value)
        else:
            raise ValueError(f"Unknown operator: {op!r}")

    where = " AND ".join(clauses) if clauses else "TRUE"
    if shared_joins:
        return where, params, ""
    joins_sql = (" " + " ".join(joins)) if joins else ""
    return where, params, joins_sql
