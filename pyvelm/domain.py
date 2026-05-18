"""Domain → SQL compiler.

A domain is `[(attr, op, value), ...]`, implicitly AND-ed. Attrs may be
dotted (`country_id.code`); the path is parsed against the model and, for
Many2one-only chains, emitted as `LEFT JOIN`s. Paths involving One2many or
Many2many in domains are not supported yet (they need `EXISTS` subquery
generation, which is the natural follow-up to this slice).

Public surface:
    domain_to_sql(domain, model_cls) -> (where, params, joins)

`where` is the SQL after `WHERE` (defaults to `TRUE`).
`joins` is the `LEFT JOIN ...` text to splice between the base table and
`WHERE` (empty when no traversal is used).
`params` are the bind values, in order.

Operators: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `like`, `ilike`.
Empty `in`/`not in` short-circuit to `FALSE`/`TRUE`.
"""
from __future__ import annotations

from typing import Any, Iterable

from .paths import M2mHop, M2oHop, O2mHop, parse_path

_SIMPLE_OPS = {"=", "!=", "<", "<=", ">", ">="}


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
) -> tuple[str, list[Any], str]:
    if not domain:
        return "TRUE", [], ""

    base_alias = f'"{model_cls._table}"'
    clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []
    # Memoize JOIN aliases per (base, attr) chain so the same traversal in
    # two leaves shares aliases — avoids redundant JOINs.
    join_aliases: dict[tuple, str] = {}
    join_counter = [0]

    from .registry import registry

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

    def _emit_exists(path, op: str, value):
        """Emit `EXISTS (...)` for a path containing at least one O2m/M2m
        hop. Each call generates a fresh subquery — consecutive collection
        leaves can match different members, which is the intuitive read.
        """
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
        if op in _SIMPLE_OPS:
            v = _coerce(leaf_field, value)
            if v is None and op == "=":
                inner_clauses.append(f"{leaf_ref} IS NULL")
            elif v is None and op == "!=":
                inner_clauses.append(f"{leaf_ref} IS NOT NULL")
            else:
                inner_clauses.append(f"{leaf_ref} {op} %s")
                inner_params.append(v)
        elif op == "in":
            values = [_coerce(leaf_field, v) for v in value]
            if not values:
                return "FALSE", []
            placeholders = ",".join(["%s"] * len(values))
            inner_clauses.append(f"{leaf_ref} IN ({placeholders})")
            inner_params.extend(values)
        elif op == "not in":
            values = [_coerce(leaf_field, v) for v in value]
            if not values:
                inner_clauses.append("TRUE")
            else:
                placeholders = ",".join(["%s"] * len(values))
                inner_clauses.append(f"{leaf_ref} NOT IN ({placeholders})")
                inner_params.extend(values)
        elif op == "like":
            inner_clauses.append(f"{leaf_ref} LIKE %s")
            inner_params.append(value)
        elif op == "ilike":
            inner_clauses.append(f"{leaf_ref} ILIKE %s")
            inner_params.append(value)
        else:
            raise ValueError(f"Unknown operator: {op!r}")

        sql_body = " ".join(froms)
        clause = (
            f"EXISTS (SELECT 1 FROM {sql_body} "
            f'WHERE {" AND ".join(inner_clauses)})'
        )
        return clause, inner_params

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
        if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3):
            raise ValueError(f"Invalid domain leaf: {leaf!r}")
        attr, op, value = leaf

        # Paths containing any O2m/M2m hop go through an EXISTS subquery.
        # Pure-M2o paths stay in the LEFT JOIN path so multiple leaves
        # on the same chain share a single join.
        if "." in attr:
            path = parse_path(model_cls, attr, registry)
            if not path.is_m2o_only():
                clause, ps = _emit_exists(path, op, value)
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
    joins_sql = (" " + " ".join(joins)) if joins else ""
    return where, params, joins_sql
