from __future__ import annotations

from typing import Any

from .registry import Registry


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
        registry: Registry,
        uid: int = 1,
        context: dict | None = None,
    ) -> None:
        self.conn = conn
        self.uid = uid
        self.context = dict(context or {})
        self.registry = registry
        self.cache = Cache()
        # In-flight transaction depth for nested savepoint support; 0 means
        # no transaction open, calls auto-commit per-statement.
        self._tx_depth: int = 0
        # Compute orchestration flag — set by compute_field, gates writes.
        self._in_compute: bool = False

    def __getitem__(self, model_name: str):
        model_cls = self.registry[model_name]
        return model_cls(self, ())

    def with_context(self, **overrides) -> "Environment":
        new = Environment(
            self.conn,
            registry=self.registry,
            uid=self.uid,
            context={**self.context, **overrides},
        )
        new.cache = self.cache
        return new

    # ------ Transactions ------

    def transaction(self):
        """Return a context manager for an atomic unit of work.

        Outer call opens a real transaction; nested calls use savepoints
        so partial work can roll back independently.  On exception the
        active scope rolls back; otherwise it commits / releases.

        This is the explicit boundary that install/migrate flows use to
        keep schema mutations atomic. CRUD calls outside any transaction
        are still effectively auto-committed because the connection is
        configured that way.
        """
        env = self

        class _TxContext:
            def __enter__(self_inner):
                if env._tx_depth == 0:
                    if env.conn.autocommit:
                        env.conn.autocommit = False
                    env._tx_opened_autocommit = False
                    env._tx_depth = 1
                    self_inner._kind = "tx"
                else:
                    sp_name = f"_pyvelm_sp{env._tx_depth}"
                    env.conn.execute(f"SAVEPOINT {sp_name}")
                    env._tx_depth += 1
                    self_inner._kind = "sp"
                    self_inner._sp_name = sp_name
                return env

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    if self_inner._kind == "tx":
                        if exc is None:
                            env.conn.commit()
                        else:
                            env.conn.rollback()
                    else:
                        sp = self_inner._sp_name
                        if exc is None:
                            env.conn.execute(f"RELEASE SAVEPOINT {sp}")
                        else:
                            env.conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                finally:
                    env._tx_depth -= 1
                    if env._tx_depth == 0:
                        # Reopen autocommit so subsequent ad-hoc statements
                        # don't sit in an implicit transaction.
                        env.conn.autocommit = True
                return False

        return _TxContext()

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

    def notify_changed(self, model_name: str, ids, fields) -> None:
        """Propagate field changes through the compute dependency graph.

        Each `(model_name, field)` change consults `_edge_index` for the
        listening compute fields. Each `HopEdge.find_source_ids` walks any
        relational hops backward to land on the source-side ids that need
        invalidation. BFS through transitive dependents:

          - drop the cache entry,
          - if the dependent is stored, recompute now and UPDATE the SQL
            column (so other sessions see the new value),
          - enqueue further dependents.
        """
        from collections import deque

        if not ids or not fields:
            return
        ids = list(ids)
        queue: deque = deque()

        def fan_out(m: str, fs, idset):
            for f in fs:
                for dep_model, dep_field, edge in self.registry._edge_index.get(
                    (m, f), []
                ):
                    affected = edge.find_source_ids(self, list(idset))
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
                recs = self.registry[m](self, tuple(new_ids))
                self.compute_field(recs, field)
            fan_out(m, [f], new_ids)
