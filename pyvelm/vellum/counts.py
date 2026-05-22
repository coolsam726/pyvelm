"""Aggregated relation counts (``with_count`` / ``count_of``)."""
from __future__ import annotations

from collections import defaultdict

from pyvelm.fields import Many2many, One2many


def apply_with_counts(env, records, field_names: tuple[str, ...]) -> None:
    """Attach ``_vellum_counts`` on *records* keyed by field name and record id."""
    if not records or not field_names:
        return
    model_name = records._name
    parent_ids = list(records._ids)
    if not parent_ids:
        return
    counts: dict[str, dict[int, int]] = {}
    for fname in field_names:
        field = records._fields.get(fname)
        if field is None:
            raise ValueError(f"{model_name} has no field {fname!r}")
        if isinstance(field, One2many):
            counts[fname] = _count_one2many(env, records, field, parent_ids)
        elif isinstance(field, Many2many):
            counts[fname] = _count_many2many(env, records, field, parent_ids)
        else:
            raise ValueError(
                f"{model_name}.{fname}: with_count supports One2many/Many2many only"
            )
    existing = getattr(records, "_vellum_counts", None) or {}
    merged = {**existing, **counts}
    object.__setattr__(records, "_vellum_counts", merged)


def _count_one2many(env, parent_cls, field, parent_ids: list[int]) -> dict[int, int]:
    comodel_cls = env.registry[field.comodel_name]
    inverse = comodel_cls._fields[field.inverse_name]
    placeholders = ",".join(["%s"] * len(parent_ids))
    rows = env.conn.execute(
        f'SELECT "{inverse.column}", COUNT(*)::int FROM "{comodel_cls._table}" '
        f'WHERE "{inverse.column}" IN ({placeholders}) '
        f'GROUP BY "{inverse.column}"',
        parent_ids,
    ).fetchall()
    out: dict[int, int] = {int(pid): 0 for pid in parent_ids}
    for parent_id, cnt in rows:
        out[int(parent_id)] = int(cnt)
    return out


def _count_many2many(env, parent_cls, field, parent_ids: list[int]) -> dict[int, int]:
    relation, col1, col2, _, _ = field.resolve_spec(parent_cls, env.registry)
    placeholders = ",".join(["%s"] * len(parent_ids))
    rows = env.conn.execute(
        f'SELECT "{col1}", COUNT(*)::int FROM "{relation}" '
        f'WHERE "{col1}" IN ({placeholders}) GROUP BY "{col1}"',
        parent_ids,
    ).fetchall()
    out: dict[int, int] = {int(pid): 0 for pid in parent_ids}
    for parent_id, cnt in rows:
        out[int(parent_id)] = int(cnt)
    return out
