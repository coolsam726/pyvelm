"""In-memory recordset helpers (Vellum collection layer)."""
from __future__ import annotations

from typing import Any, Callable


def _normalize_mem_where(
    field: str, op: str | Any = None, value: Any = None
) -> tuple[str, str, Any]:
    if op is None:
        return (field, "=", value)
    if value is None and op not in (
        "=",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "in",
        "not in",
        "like",
        "ilike",
    ):
        return (field, "=", op)
    return (field, op, value)


def _match_leaf(record, leaf: tuple[str, str, Any]) -> bool:
    field, op, expected = leaf
    actual = getattr(record, field)
    if hasattr(actual, "_ids"):
        if not actual._ids:
            actual_val = None
        elif len(actual._ids) == 1:
            actual_val = actual._ids[0]
        else:
            actual_val = set(actual._ids)
    else:
        actual_val = actual

    if op == "=":
        return actual_val == expected
    if op == "!=":
        return actual_val != expected
    if op == "<":
        return actual_val is not None and actual_val < expected
    if op == "<=":
        return actual_val is not None and actual_val <= expected
    if op == ">":
        return actual_val is not None and actual_val > expected
    if op == ">=":
        return actual_val is not None and actual_val >= expected
    if op == "in":
        return actual_val in (expected or [])
    if op == "not in":
        return actual_val not in (expected or [])
    if op == "like":
        return _sql_like(actual_val, expected, case_sensitive=True)
    if op == "ilike":
        return _sql_like(actual_val, expected, case_sensitive=False)
    raise ValueError(f"Unsupported in-memory operator {op!r}")


def _sql_like(actual: Any, pattern: str, *, case_sensitive: bool) -> bool:
    if actual is None:
        return False
    text = str(actual)
    pat = str(pattern)
    if not case_sensitive:
        text = text.lower()
        pat = pat.lower()
    if pat.endswith("%") and not pat.startswith("%"):
        return text.startswith(pat[:-1])
    if pat.startswith("%") and not pat.endswith("%"):
        return text.endswith(pat[1:])
    if pat.startswith("%") and pat.endswith("%") and len(pat) >= 2:
        return pat[1:-1] in text
    return text == pat


def filter_recordset(rs, predicate: Callable) -> Any:
    cls = rs.__class__
    kept = tuple(rid for rid in rs._ids if predicate(cls(rs.env, (rid,))))
    return cls(rs.env, kept)


def where_recordset(rs, field: str, op: str | Any = None, value: Any = None):
    leaf = _normalize_mem_where(field, op, value)

    def _pred(rec):
        return _match_leaf(rec, leaf)

    return filter_recordset(rs, _pred)


def wrap(rs):
    """Return ``rs`` unchanged; documents the optional adapter entry point."""
    return rs
