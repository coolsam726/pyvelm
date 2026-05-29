"""Domain → SQL compiler.

A domain is a list of leaves and/or Odoo-style **prefix operators** ``&``,
``|``, ``!``. Adjacent leaves without operators are implicitly **AND**ed
(see ``normalize_domain``). The legacy ``("__or__", "=", [sub_leaves…])``
leaf is accepted and expanded to ``|`` groups before compilation.

Attrs may be dotted (``country_id.code``, ``tag_ids.name``); paths compile
to memoized ``LEFT JOIN``s (pure Many2one chains) or per-leaf ``EXISTS``
subqueries (One2many / Many2many hops).

Public surface:
    domain_to_sql(domain, model_cls) -> (where, params, joins)
    normalize_domain(domain) -> list
    iter_domain_leaves(domain) -> iterator of leaf tuples

Operators on leaves: ``=``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``,
``not in``, ``like``, ``ilike``. Empty ``in`` / ``not in`` short-circuit.

Collection paths accept an optional fourth element — ``{"all": True}`` —
for universal quantification (``NOT EXISTS`` over members that fail).
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator

from .paths import M2mHop, M2oHop, O2mHop, parse_path

_SIMPLE_OPS = {"=", "!=", "<", "<=", ">", ">="}
_POLISH_OPS = frozenset({"&", "|", "!"})
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


def is_domain_leaf(token: Any) -> bool:
    """True when *token* is a ``(field, op, value[, opts])`` leaf."""
    if not isinstance(token, (list, tuple)) or len(token) not in (3, 4):
        return False
    if not isinstance(token[0], str):
        return False
    return token[0] not in _POLISH_OPS


def expand_or_groups(domain: list) -> list:
    """Expand legacy ``("__or__", …)`` leaves into ``|`` prefix groups."""
    out: list = []
    for item in domain:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 3
            and item[0] == "__or__"
        ):
            subs = list(item[2] or [])
            if not subs:
                continue
            if len(subs) == 1:
                out.append(subs[0])
            else:
                out.extend(["|"] * (len(subs) - 1))
                out.extend(subs)
        else:
            out.append(item)
    return out


def normalize_domain(domain: list) -> list:
    """Make implicit AND explicit (Odoo ``normalize_domain`` semantics)."""
    if not domain:
        return []
    result: list = []
    expected = 1
    op_arity = {"!": 1, "&": 2, "|": 2}
    for token in domain:
        if expected == 0:
            result.insert(0, "&")
            expected = 1
        if is_domain_leaf(token):
            result.append(tuple(token))
            expected -= 1
        elif token in op_arity:
            result.append(token)
            expected += op_arity[token] - 1
        else:
            raise ValueError(f"Invalid domain token {token!r}")
    if expected:
        raise ValueError(f"Invalid domain {domain!r}")
    return result


def _parse_polish(domain: list, pos: int = 0):
    """Parse normalized prefix domain into an expression tree."""
    if pos >= len(domain):
        raise ValueError("Unexpected end of domain")
    tok = domain[pos]
    if tok == "!":
        child, pos = _parse_polish(domain, pos + 1)
        return ("!", child), pos
    if tok == "&":
        left, pos = _parse_polish(domain, pos + 1)
        right, pos = _parse_polish(domain, pos)
        return ("&", left, right), pos
    if tok == "|":
        left, pos = _parse_polish(domain, pos + 1)
        right, pos = _parse_polish(domain, pos)
        return ("|", left, right), pos
    if is_domain_leaf(tok):
        return ("leaf", tok), pos + 1
    raise ValueError(f"Invalid domain token {tok!r} at position {pos}")


def iter_domain_leaves(domain: Iterable) -> Iterator[tuple]:
    """Yield every leaf tuple in *domain* (after normalize / ``__or__`` expand)."""
    if not domain:
        return
    norm = normalize_domain(expand_or_groups(list(domain)))
    tree, end = _parse_polish(norm, 0)
    if end != len(norm):
        raise ValueError("Trailing tokens in domain")

    def _walk(node):
        kind = node[0]
        if kind == "leaf":
            yield node[1]
        elif kind == "!":
            yield from _walk(node[1])
        else:
            yield from _walk(node[1])
            yield from _walk(node[2])

    yield from _walk(tree)


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

    domain_norm = normalize_domain(expand_or_groups(list(domain)))
    tree, end = _parse_polish(domain_norm, 0)
    if end != len(domain_norm):
        raise ValueError("Trailing tokens in domain")

    base_alias = f'"{model_cls._table}"'
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
        """Emit ``EXISTS (…)`` for a path containing at least one O2m/M2m hop."""
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
            elif isinstance(hop, M2oHop):
                tgt = registry[hop.target_model]
                alias = f"_e{suffix}_{i}"
                if i == 0:
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

        assert prev_alias is not None
        leaf_field = _resolve_leaf_field(path)
        leaf_col = leaf_field.column if leaf_field is not None else "id"
        leaf_ref = f'{prev_alias}."{leaf_col}"'

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
        """Return (qualified_column_sql, field_or_None) for ``attr``."""
        if "." not in attr:
            col, field = _resolve_simple(model_cls, attr)
            return f'{base_alias}."{col}"', field
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

    def _compile_leaf(leaf) -> tuple[str, list[Any]]:
        attr, op, value, universal = _parse_leaf(leaf)
        leaf_params: list[Any] = []

        if universal and "." not in attr:
            raise ValueError(
                f"{{'all': True}} only applies to collection paths, got {attr!r}"
            )
        if "." in attr:
            path = parse_path(model_cls, attr, registry)
            if not path.is_m2o_only():
                clause, ps = _emit_exists(path, op, value, universal=universal)
                return clause, ps

        col_sql, field = _leaf_ref(attr)

        if op in _SIMPLE_OPS:
            v = _coerce(field, value)
            if v is None and op == "=":
                return f"{col_sql} IS NULL", leaf_params
            if v is None and op == "!=":
                return f"{col_sql} IS NOT NULL", leaf_params
            leaf_params.append(v)
            return f"{col_sql} {op} %s", leaf_params
        if op == "in":
            values = [_coerce(field, v) for v in value]
            if not values:
                return "FALSE", leaf_params
            placeholders = ",".join(["%s"] * len(values))
            leaf_params.extend(values)
            return f"{col_sql} IN ({placeholders})", leaf_params
        if op == "not in":
            values = [_coerce(field, v) for v in value]
            if not values:
                return "TRUE", leaf_params
            placeholders = ",".join(["%s"] * len(values))
            leaf_params.extend(values)
            return f"{col_sql} NOT IN ({placeholders})", leaf_params
        if op == "like":
            leaf_params.append(value)
            return f"{col_sql} LIKE %s", leaf_params
        if op == "ilike":
            leaf_params.append(value)
            return f"{col_sql} ILIKE %s", leaf_params
        raise ValueError(f"Unknown operator: {op!r}")

    def _compile_tree(node) -> tuple[str, list[Any]]:
        kind = node[0]
        if kind == "leaf":
            clause, leaf_params = _compile_leaf(node[1])
            params.extend(leaf_params)
            return clause, leaf_params
        if kind == "!":
            clause, leaf_params = _compile_tree(node[1])
            return f"NOT ({clause})", leaf_params
        if kind in ("&", "|"):
            left_clause, _ = _compile_tree(node[1])
            right_clause, _ = _compile_tree(node[2])
            joiner = " AND " if kind == "&" else " OR "
            return f"({left_clause}{joiner}{right_clause})", []
        raise ValueError(f"Unknown domain node {kind!r}")

    where, _ = _compile_tree(tree)
    if shared_joins:
        return where, params, ""
    joins_sql = (" " + " ".join(joins)) if joins else ""
    return where, params, joins_sql
