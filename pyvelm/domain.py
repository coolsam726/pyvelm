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
    capabilities=None,
) -> tuple[str, list[Any], str]:
    """Compile a domain to SQL.

    When ``joins`` / ``join_aliases`` / ``join_counter`` are passed, JOIN
    emission appends to those shared structures (used by the report compiler
    so column and filter paths reuse the same ``_jN`` aliases). In that
    mode the third return value is always ``""`` — read ``joins`` instead.
    """
    from .domain_sa import domain_to_sql as _compile_domain_to_sql

    return _compile_domain_to_sql(
        domain,
        model_cls,
        registry,
        capabilities=capabilities,
        joins=joins,
        join_aliases=join_aliases,
        join_counter=join_counter,
    )
