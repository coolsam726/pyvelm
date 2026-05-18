from __future__ import annotations

from typing import Any

from .registry import Registry, registry as default_registry


_MISSING = object()


class Cache:
    """Field values keyed by (model_name, record_id, field_name).

    Cache lives on the Environment, not on records. This is what makes
    computed-field invalidation tractable: invalidation is a key-deletion
    pass, not a graph walk over instance state.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, int, str], Any] = {}

    def get(self, model_name: str, record_id: int, field_name: str) -> Any:
        return self._data[(model_name, record_id, field_name)]

    def set(self, model_name: str, record_id: int, field_name: str, value: Any) -> None:
        self._data[(model_name, record_id, field_name)] = value

    def contains(self, model_name: str, record_id: int, field_name: str) -> bool:
        return (model_name, record_id, field_name) in self._data

    def invalidate(
        self,
        model_name: str | None = None,
        ids: list[int] | None = None,
        fields: list[str] | None = None,
    ) -> None:
        if model_name is None and ids is None and fields is None:
            self._data.clear()
            return
        to_delete = []
        for key in self._data:
            m, i, f = key
            if model_name is not None and m != model_name:
                continue
            if ids is not None and i not in ids:
                continue
            if fields is not None and f not in fields:
                continue
            to_delete.append(key)
        for key in to_delete:
            del self._data[key]


class Environment:
    """First-class context threaded through every recordset.

    Carries DB connection, user id, ad-hoc context dict, the registry,
    and the value cache. Recordsets are cheap views over an Environment.
    """

    def __init__(
        self,
        conn,
        uid: int = 1,
        context: dict | None = None,
        registry: Registry | None = None,
    ) -> None:
        self.conn = conn
        self.uid = uid
        self.context = dict(context or {})
        self.registry = registry or default_registry
        self.cache = Cache()
        self._in_compute = False

    def __getitem__(self, model_name: str):
        model_cls = self.registry[model_name]
        return model_cls(self, ())

    def with_context(self, **overrides) -> "Environment":
        new = Environment(self.conn, self.uid, {**self.context, **overrides}, self.registry)
        new.cache = self.cache
        return new

    # ------ Computed-field orchestration ------

    def compute_field(self, record, field) -> None:
        """Run a compute method on the records that need it.

        Computes are bulk-friendly: the method sees the whole recordset and
        is expected to iterate. For stored fields, cached values flush to
        SQL after the method returns; for non-stored, the cache write is
        the final state until the next invalidation.
        """
        model_cls = type(record)
        # Expand to all of record's ids — compute is bulk by convention.
        recs = model_cls(self, record._ids)
        prev = self._in_compute
        self._in_compute = True
        try:
            method = getattr(recs, field.compute)
            method()
        finally:
            self._in_compute = prev
        if field.is_stored:
            for rid in recs._ids:
                if not self.cache.contains(model_cls._name, rid, field.name):
                    raise RuntimeError(
                        f"Compute {field.compute!r} did not set "
                        f"{model_cls._name}.{field.name} for id={rid}"
                    )
                value = self.cache.get(model_cls._name, rid, field.name)
                self.conn.execute(
                    f'UPDATE "{model_cls._table}" SET "{field.column}" = %s '
                    f'WHERE "id" = %s',
                    [field.to_sql_param(value), rid],
                )

    def _reverse_m2o(self, model_name: str, m2o_attr: str, source_ids) -> list[int]:
        """Find records of `model_name` whose `m2o_attr` FK is in `source_ids`."""
        if not source_ids:
            return []
        target_cls = self.registry[model_name]
        col = target_cls._fields[m2o_attr].column
        placeholders = ",".join(["%s"] * len(source_ids))
        rows = self.conn.execute(
            f'SELECT "id" FROM "{target_cls._table}" '
            f'WHERE "{col}" IN ({placeholders})',
            list(source_ids),
        ).fetchall()
        return [r[0] for r in rows]

    def notify_changed(self, model_name: str, ids, fields) -> None:
        """Propagate field changes through the compute dependency graph.

        Walks dependents BFS-style. For each dependent (m, f, idset):
          - drop the cache entry,
          - if f is stored, recompute now and UPDATE the SQL column,
          - regardless, queue further dependents.
        """
        from collections import deque

        if not ids or not fields:
            return
        ids = list(ids)
        queue: deque = deque()

        def fan_out(m: str, fs, idset):
            for f in fs:
                for dep_model, dep_field in self.registry._direct_deps.get(
                    (m, f), []
                ):
                    queue.append((dep_model, dep_field, set(idset)))
                for dep_model, m2o_attr, dep_field in self.registry._m2o_deps.get(
                    (m, f), []
                ):
                    affected = self._reverse_m2o(dep_model, m2o_attr, idset)
                    if affected:
                        queue.append((dep_model, dep_field, set(affected)))

        fan_out(model_name, fields, ids)

        seen: dict[tuple[str, str], set[int]] = {}
        while queue:
            m, f, idset = queue.popleft()
            key = (m, f)
            already = seen.get(key, set())
            new_ids = idset - already
            if not new_ids:
                continue
            seen[key] = already | new_ids
            self.cache.invalidate(model_name=m, ids=list(new_ids), fields=[f])
            field = self.registry[m]._fields[f]
            if field.is_stored:
                # Recompute now so the column is up-to-date for SQL queries.
                recs = self.registry[m](self, tuple(new_ids))
                self.compute_field(recs, field)
            fan_out(m, [f], new_ids)
