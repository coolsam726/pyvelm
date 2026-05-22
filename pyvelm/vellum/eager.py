"""Eager-loading (``with_``) for Vellum query builders."""
from __future__ import annotations

from collections import defaultdict

from pyvelm.fields import (
    Many2many,
    Many2one,
    One2many,
    _store_collection_cache,
)


def eager_load(env, records, paths: tuple[str, ...]) -> None:
    """Prefetch relational paths onto ``env.cache`` after a main ``search``."""
    if not records or not paths:
        return
    model_cls = records.__class__
    for raw in paths:
        tokens = raw.split(".")
        if not tokens or not all(tokens):
            raise ValueError(f"Invalid eager path {raw!r}")
        _prefetch_path(env, model_cls, records._ids, tokens, visited=set())


def _prefetch_path(
    env,
    model_cls,
    parent_ids: tuple[int, ...],
    tokens: list[str],
    *,
    visited: set[tuple[str, str]],
) -> None:
    if not parent_ids:
        return
    field_name = tokens[0]
    field = model_cls._fields.get(field_name)
    if field is None:
        raise ValueError(
            f"{model_cls._name} has no field {field_name!r} for eager load"
        )
    key = (model_cls._name, field_name)
    if key in visited:
        return
    visited.add(key)

    if isinstance(field, Many2one):
        recs = model_cls(env, parent_ids)
        recs._read([field_name])
        if len(tokens) == 1:
            return
        comodel_cls = env.registry[field.comodel_name]
        child_ids: set[int] = set()
        for rid in parent_ids:
            raw = env.cache.get(model_cls._name, rid, field_name)
            if raw is not None:
                child_ids.add(int(raw))
        _prefetch_path(
            env, comodel_cls, tuple(child_ids), tokens[1:], visited=visited
        )
        return

    if isinstance(field, One2many):
        _prefetch_one2many(env, model_cls, parent_ids, field)
        if len(tokens) == 1:
            return
        comodel_cls = env.registry[field.comodel_name]
        child_ids: list[int] = []
        for rid in parent_ids:
            cached = env.cache.get(model_cls._name, rid, field_name)
            if isinstance(cached, tuple):
                child_ids.extend(cached)
        _prefetch_path(
            env,
            comodel_cls,
            tuple(dict.fromkeys(child_ids)),
            tokens[1:],
            visited=visited,
        )
        return

    if isinstance(field, Many2many):
        _prefetch_many2many(env, model_cls, parent_ids, field)
        if len(tokens) == 1:
            return
        comodel_cls = env.registry[field.comodel_name]
        child_ids = []
        for rid in parent_ids:
            cached = env.cache.get(model_cls._name, rid, field_name)
            if isinstance(cached, tuple):
                child_ids.extend(cached)
        _prefetch_path(
            env,
            comodel_cls,
            tuple(dict.fromkeys(child_ids)),
            tokens[1:],
            visited=visited,
        )
        return

    raise ValueError(
        f"Cannot eager-load {model_cls._name}.{field_name} "
        f"({type(field).__name__})"
    )


def _prefetch_one2many(env, parent_cls, parent_ids: tuple[int, ...], field) -> None:
    comodel_cls = env.registry[field.comodel_name]
    inverse = comodel_cls._fields[field.inverse_name]
    placeholders = ",".join(["%s"] * len(parent_ids))
    rows = env.conn.execute(
        f'SELECT "{inverse.column}", "id" FROM "{comodel_cls._table}" '
        f'WHERE "{inverse.column}" IN ({placeholders}) '
        f'ORDER BY "{inverse.column}", "id"',
        list(parent_ids),
    ).fetchall()
    grouped: dict[int, list[int]] = defaultdict(list)
    for parent_id, child_id in rows:
        grouped[int(parent_id)].append(int(child_id))
    cache = env.cache
    for pid in parent_ids:
        ids = tuple(grouped.get(int(pid), ()))
        _store_collection_cache(cache, parent_cls._name, int(pid), field.name, ids)


def _prefetch_many2many(env, parent_cls, parent_ids: tuple[int, ...], field) -> None:
    relation, col1, col2, _, _ = field.resolve_spec(parent_cls, env.registry)
    placeholders = ",".join(["%s"] * len(parent_ids))
    rows = env.conn.execute(
        f'SELECT "{col1}", "{col2}" FROM "{relation}" '
        f'WHERE "{col1}" IN ({placeholders}) '
        f'ORDER BY "{col1}", "{col2}"',
        list(parent_ids),
    ).fetchall()
    grouped: dict[int, list[int]] = defaultdict(list)
    for parent_id, target_id in rows:
        grouped[int(parent_id)].append(int(target_id))
    cache = env.cache
    for pid in parent_ids:
        ids = tuple(grouped.get(int(pid), ()))
        _store_collection_cache(cache, parent_cls._name, int(pid), field.name, ids)
