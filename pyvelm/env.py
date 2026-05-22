from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .registry import Registry

if TYPE_CHECKING:
    from pyvelm.vellum.query import QueryBuilder


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
        # ACL bypass flag — flipped temporarily while resolving the
        # current user's groups or evaluating ir.model.access rows, to
        # avoid infinite recursion through check_access.
        self._acl_bypass: bool = False
        # Per-(model, perm) access-decision cache so every field read
        # doesn't re-query ir.model.access. Invalidate on logout / uid
        # switch by constructing a fresh Environment.
        self._access_cache: dict[tuple[str, str], bool] = {}

    def __getitem__(self, model_name: str):
        model_cls = self.registry[model_name]
        return model_cls(self, ())

    def query(self, model_name: str) -> "QueryBuilder":
        """Vellum query builder for *model_name* (the registry's merged class).

        Prefer this over importing a model class from a specific module when
        models are extended via ``_inherit`` — the technical name is stable;
        the Python class in any one ``models/`` file may not be.

        Example::

            posts = env.query("blog.post").where("views", ">", 100).get()
        """
        from pyvelm.vellum.query import QueryBuilder

        model_cls = self.registry[model_name]
        return QueryBuilder(model_cls=model_cls, env=self)

    def with_context(self, **overrides) -> "Environment":
        new = Environment(
            self.conn,
            registry=self.registry,
            uid=self.uid,
            context={**self.context, **overrides},
        )
        new.cache = self.cache
        return new

    # ------ Company ------

    @property
    def company_id(self) -> int | None:
        """Active company scope, or None for no scoping.

        Set via `with_company(id)` or by passing ``company_id`` to
        `with_context`. Superuser and ACL-bypass paths can also check
        this to know the intended tenant without having the restriction
        applied.
        """
        return self.context.get("company_id")

    def with_company(self, company_id: int | None) -> "Environment":
        """Return a copy of this environment scoped to *company_id*.

        Passing ``None`` removes any existing company scope (useful for
        cross-company superuser operations).
        """
        return self.with_context(company_id=company_id)

    # ------ ACL ------

    SUPERUSER_ID = 1

    def is_superuser(self) -> bool:
        """Stage 5 convention: uid=1 bypasses every ACL check.

        Matches Odoo's `SUPERUSER_ID`. The installer, migration scripts,
        and module install hooks all run as superuser.
        """
        return self.uid == self.SUPERUSER_ID

    @property
    def user_group_ids(self) -> set[int]:
        """The set of `res.groups` ids the current user belongs to.

        Cached on the Environment for the request lifetime so
        per-statement ACL checks don't re-query.
        """
        cached = getattr(self, "_user_groups_cache", None)
        if cached is not None:
            return cached
        if self.uid is None or "res.users" not in self.registry:
            result: set[int] = set()
        else:
            # Bypass ACL on this lookup — chicken-and-egg otherwise.
            prev = self._acl_bypass
            self._acl_bypass = True
            try:
                user = self["res.users"].browse(self.uid)
                # If the recorded uid doesn't exist (deleted user, etc),
                # treat as anonymous.
                if not self["res.users"].search([("id", "=", self.uid)]):
                    result = set()
                else:
                    result = set(user.group_ids.ids)
            finally:
                self._acl_bypass = prev
        self._user_groups_cache = result
        return result

    def check_access(self, model_name: str, perm: str) -> None:
        """Raise PermissionError if the current user lacks `perm` on
        `model_name`. No-op for superuser or while bypass is set.

        `perm` is one of: read / write / create / unlink.
        """
        if self.is_superuser() or self._acl_bypass:
            return
        if "ir.model.access" not in self.registry:
            # ACL machinery not installed yet (e.g. early in install).
            return
        cache_key = (model_name, perm)
        cached = self._access_cache.get(cache_key)
        if cached is True:
            return
        if cached is False:
            raise PermissionError(
                f"Access denied: {perm} on {model_name} (uid={self.uid})"
            )
        Access = self["ir.model.access"]
        # Bypass ACL on the access-table lookup itself — otherwise
        # recursion. Same reason `user_group_ids` flips the bypass.
        prev = self._acl_bypass
        self._acl_bypass = True
        try:
            domain = [
                ("model", "=", model_name),
                (f"perm_{perm}", "=", True),
            ]
            if self.uid is None:
                # Anonymous: only grants with group_id=None apply.
                domain.append(("group_id", "=", None))
            else:
                # Authenticated: any grant with group_id=None or in the
                # user's groups applies. We split into two searches to
                # avoid the `IN (NULL, ...)` SQL-NULL pitfall.
                ids = self.user_group_ids
                anyone = Access.search(domain + [("group_id", "=", None)],
                                       limit=1)
                granted = bool(anyone)
                if not granted and ids:
                    grouped = Access.search(
                        domain + [("group_id", "in", list(ids))], limit=1,
                    )
                    granted = bool(grouped)
                self._access_cache[cache_key] = granted
                if not granted:
                    raise PermissionError(
                        f"Access denied: {perm} on {model_name} "
                        f"(uid={self.uid})"
                    )
                return
            # Anonymous branch.
            granted = bool(Access.search(domain, limit=1))
            self._access_cache[cache_key] = granted
            if not granted:
                raise PermissionError(
                    f"Access denied: {perm} on {model_name} (anonymous)"
                )
        finally:
            self._acl_bypass = prev

    def collect_record_rules(self, model_name: str, perm: str) -> list:
        """Return the union of domain leaves to AND-inject into
        searches on `model_name` for `perm`. Empty for superuser /
        bypass / when ir.rule isn't installed."""
        if self.is_superuser() or self._acl_bypass:
            return []
        if "ir.rule" not in self.registry:
            return []
        Rule = self["ir.rule"]
        prev = self._acl_bypass
        self._acl_bypass = True
        try:
            domain = [
                ("model", "=", model_name),
                (f"perm_{perm}", "=", True),
            ]
            if self.uid is None:
                # Anonymous: only global rules apply.
                domain.append(("group_id", "=", None))
                rules = Rule.search(domain)
            else:
                ids = self.user_group_ids
                # Global rules + rules for any of our groups.
                global_rules = Rule.search(domain + [("group_id", "=", None)])
                if ids:
                    group_rules = Rule.search(
                        domain + [("group_id", "in", list(ids))],
                    )
                else:
                    group_rules = global_rules.__class__(self, ())
                rules = global_rules
                if group_rules:
                    rules = global_rules.__class__(
                        self, tuple({*global_rules.ids, *group_rules.ids})
                    )
            # Read domains while still under bypass — accessing
            # `r.domain` triggers _read on ir.rule, which re-enters
            # check_access. Without bypass, that recurses and denies.
            import json
            out: list = []
            for r in rules:
                raw = json.loads(r.domain)
                out.extend(self._resolve_rule_leaves(raw))
        finally:
            self._acl_bypass = prev

        return out

    def _resolve_rule_leaves(self, raw_domain: list) -> list:
        """Substitute {placeholder: name} dicts with env-side values."""
        resolved = []
        for leaf in raw_domain:
            if not isinstance(leaf, (list, tuple)):
                resolved.append(leaf)
                continue
            attr, op, value = leaf
            # Single placeholder dict.
            if isinstance(value, dict) and "placeholder" in value:
                value = self._resolve_placeholder(value["placeholder"])
            # List value that may contain placeholder dicts (e.g. "in" operator).
            elif isinstance(value, list):
                value = [
                    self._resolve_placeholder(item["placeholder"])
                    if isinstance(item, dict) and "placeholder" in item
                    else item
                    for item in value
                ]
            resolved.append((attr, op, value))
        return resolved

    def _resolve_placeholder(self, ph: str):
        """Return the env-side value for a placeholder name."""
        if ph in ("uid", "user_id"):
            return self.uid
        if ph == "company_id":
            # Apps can still write per-group ir.rules that reference
            # the active company. The model-level filter applied by
            # `BaseModel.search` for `_company_scoped` models is the
            # default mechanism; this placeholder is for the
            # finer-grained case.
            return self.company_id
        raise ValueError(f"Unknown ir.rule placeholder {ph!r}")

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
