from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Iterator

from .domain import domain_to_sql
from .fields import Field
from .registry import registry


class MetaModel(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)

        # Collect fields from this class and its bases.
        fields: dict[str, Field] = {}
        for base in reversed(bases):
            fields.update(getattr(base, "_fields", {}))
        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, Field):
                attr_value.bind(namespace.get("_name") or "", attr_name)
                fields[attr_name] = attr_value
        cls._fields = fields

        # Defer table name and registry binding to subclasses with _name.
        if namespace.get("_name"):
            cls._table = namespace.get("_table") or namespace["_name"].replace(".", "_")
            for f in fields.values():
                f.model_name = cls._name
            # Bind compute methods to their fields: copy @depends paths.
            for fname, field in fields.items():
                if not field.compute:
                    continue
                method = namespace.get(field.compute) or getattr(cls, field.compute, None)
                if method is None:
                    raise ValueError(
                        f"{cls._name}.{fname}: compute method "
                        f"{field.compute!r} not found"
                    )
                deps = getattr(method, "_pyvelm_depends", None)
                if deps is None:
                    raise ValueError(
                        f"{cls._name}.{fname}: compute method "
                        f"{field.compute!r} must be decorated with @depends(...)"
                    )
                field.depends_on = tuple(deps)
            registry.register(cls)
        return cls


class BaseModel(metaclass=MetaModel):
    """Recordset-is-the-model.

    An instance carries an env and a tuple of ids. Length 0 = empty
    recordset, 1 = singleton, >1 = multi-record. Field descriptors
    enforce singleton on access.
    """

    _name: str | None = None
    _table: str | None = None
    _fields: dict[str, Field] = {}

    def __init__(self, env, ids: Iterable[int] = ()) -> None:
        self.env = env
        self._ids: tuple[int, ...] = tuple(ids)

    if TYPE_CHECKING:
        # Static-analysis-only stubs. Field descriptors + the metaclass
        # mean every model has attributes Pylance/Pyright can't enumerate;
        # the descriptor protocol resolves them at runtime, so these
        # methods are never actually called. Telling the type checker
        # "any attr is Any" (both read and write) silences descriptor
        # false positives without changing runtime behavior. Real typos
        # still raise AttributeError at runtime via the cache/descriptor
        # chain, or ValueError "Unknown field" from write/create.
        def __getattr__(self, name: str) -> Any: ...
        def __setattr__(self, name: str, value: Any) -> None: ...

    # ------ recordset protocol ------

    def __iter__(self) -> Iterator["BaseModel"]:
        for rid in self._ids:
            yield self.__class__(self.env, (rid,))

    def __len__(self) -> int:
        return len(self._ids)

    def __bool__(self) -> bool:
        return bool(self._ids)

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, BaseModel)
            and other._name == self._name
            and set(other._ids) == set(self._ids)
        )

    def __hash__(self) -> int:
        return hash((self._name, self._ids))

    def __repr__(self) -> str:
        return f"{self._name}({list(self._ids)})"

    @property
    def id(self) -> int:
        self.ensure_one()
        return self._ids[0]

    @property
    def ids(self) -> list[int]:
        return list(self._ids)

    def ensure_one(self) -> None:
        if len(self._ids) != 1:
            raise ValueError(
                f"Expected singleton on {self._name}, got recordset of size {len(self._ids)}"
            )

    def browse(self, ids) -> "BaseModel":
        if isinstance(ids, int):
            ids = (ids,)
        return self.__class__(self.env, tuple(ids))

    # ------ DDL ------

    @classmethod
    def _setup_table(cls, conn) -> None:
        cols = ['"id" SERIAL PRIMARY KEY']
        for f in cls._fields.values():
            if not f.is_stored:
                continue
            cols.append(f.column_ddl())
        ddl = f'CREATE TABLE IF NOT EXISTS "{cls._table}" ({", ".join(cols)})'
        conn.execute(ddl)

    @classmethod
    def _drop_table(cls, conn) -> None:
        conn.execute(f'DROP TABLE IF EXISTS "{cls._table}" CASCADE')

    @classmethod
    def _validate_relations(cls, registry) -> None:
        """Check that relational fields point at known models / fields."""
        from .fields import Many2many, Many2one, One2many

        for f in cls._fields.values():
            if isinstance(f, One2many):
                if f.comodel_name not in registry:
                    raise ValueError(
                        f"{cls._name}.{f.name} references unknown model {f.comodel_name!r}"
                    )
                comodel = registry[f.comodel_name]
                inverse = comodel._fields.get(f.inverse_name)
                if not isinstance(inverse, Many2one):
                    raise ValueError(
                        f"{cls._name}.{f.name}: inverse {f.inverse_name!r} must be "
                        f"a Many2one on {f.comodel_name}"
                    )
                if inverse.comodel_name != cls._name:
                    raise ValueError(
                        f"{cls._name}.{f.name}: inverse "
                        f"{f.comodel_name}.{f.inverse_name} points at "
                        f"{inverse.comodel_name!r}, not {cls._name!r}"
                    )
            elif isinstance(f, Many2many):
                if f.comodel_name not in registry:
                    raise ValueError(
                        f"{cls._name}.{f.name} references unknown model {f.comodel_name!r}"
                    )

    @classmethod
    def _setup_relation_tables(cls, conn, registry, created: set[str]) -> None:
        """Create junction tables for Many2many fields. Symmetric pairs dedupe."""
        from .fields import Many2many

        for f in cls._fields.values():
            if not isinstance(f, Many2many):
                continue
            relation, col1, col2, this_table, other_table = f.resolve_spec(cls, registry)
            if relation in created:
                continue
            target = registry[f.comodel_name]
            ddl = (
                f'CREATE TABLE IF NOT EXISTS "{relation}" ('
                f'"{col1}" integer NOT NULL REFERENCES "{this_table}"("id") ON DELETE CASCADE, '
                f'"{col2}" integer NOT NULL REFERENCES "{target._table}"("id") ON DELETE CASCADE, '
                f'PRIMARY KEY ("{col1}", "{col2}"))'
            )
            conn.execute(ddl)
            created.add(relation)

    @classmethod
    def _setup_foreign_keys(cls, conn, registry) -> None:
        # Imported here to avoid a top-level cycle with fields.py.
        from .fields import Many2one

        for f in cls._fields.values():
            if not isinstance(f, Many2one):
                continue
            if f.comodel_name not in registry:
                raise ValueError(
                    f"{cls._name}.{f.name} references unknown model {f.comodel_name!r}"
                )
            target = registry[f.comodel_name]
            constraint = f"{cls._table}_{f.column}_fkey"
            conn.execute(
                f'ALTER TABLE "{cls._table}" DROP CONSTRAINT IF EXISTS "{constraint}"'
            )
            conn.execute(
                f'ALTER TABLE "{cls._table}" ADD CONSTRAINT "{constraint}" '
                f'FOREIGN KEY ("{f.column}") REFERENCES "{target._table}"("id") '
                f"ON DELETE {f.ondelete}"
            )

    # ------ CRUD ------

    def _split_vals(self, vals: dict[str, Any]) -> tuple[dict, dict]:
        """Split vals into (column_vals, m2m_vals). Validates names."""
        from .fields import Many2many

        column_vals: dict[str, Any] = {}
        m2m_vals: dict[str, Any] = {}
        for fname, value in vals.items():
            if fname not in self._fields:
                raise ValueError(f"Unknown field {fname!r} on {self._name}")
            field = self._fields[fname]
            if isinstance(field, Many2many):
                m2m_vals[fname] = value
            elif field.is_stored:
                column_vals[fname] = value
            else:
                raise ValueError(
                    f"{self._name}.{fname} is not stored; "
                    f"cannot be written directly"
                )
        return column_vals, m2m_vals

    def _apply_m2m(self, parent_ids: list[int], m2m_vals: dict[str, Any]) -> None:
        """Replace junction-table rows for each (field, parent_id) pair."""
        for fname, value in m2m_vals.items():
            field = self._fields[fname]
            relation, col1, col2, _, _ = field.resolve_spec(
                type(self), self.env.registry
            )
            target_ids = field.normalize_ids(value)
            for parent_id in parent_ids:
                self.env.conn.execute(
                    f'DELETE FROM "{relation}" WHERE "{col1}" = %s', [parent_id]
                )
                if not target_ids:
                    continue
                values_sql = ",".join(["(%s, %s)"] * len(target_ids))
                params: list[int] = []
                for tid in target_ids:
                    params.extend([parent_id, tid])
                self.env.conn.execute(
                    f'INSERT INTO "{relation}" ("{col1}", "{col2}") VALUES {values_sql}',
                    params,
                )

    def create(self, vals: dict[str, Any]) -> "BaseModel":
        column_vals, m2m_vals = self._split_vals(vals)
        cols, params = [], []
        for fname, value in column_vals.items():
            field = self._fields[fname]
            cols.append(f'"{field.column}"')
            params.append(field.to_sql_param(value))
        if cols:
            sql = (
                f'INSERT INTO "{self._table}" ({", ".join(cols)}) '
                f'VALUES ({", ".join(["%s"] * len(cols))}) RETURNING "id"'
            )
        else:
            sql = f'INSERT INTO "{self._table}" DEFAULT VALUES RETURNING "id"'
        cur = self.env.conn.execute(sql, params)
        new_id = cur.fetchone()[0]
        # Seed cache with the normalized (SQL-shape) value, so Many2one
        # caches the int FK, not whatever the user passed in.
        for fname, value in column_vals.items():
            self.env.cache.set(
                self._name, new_id, fname, self._fields[fname].to_sql_param(value)
            )
        # M2M rows after the parent exists.
        new_record = self.__class__(self.env, (new_id,))
        if m2m_vals:
            new_record._apply_m2m([new_id], m2m_vals)
        # Initial-populate stored compute fields in topo order. Non-stored
        # are lazy (next read triggers them).
        stored_order = self.env.registry._stored_compute_order.get(self._name, [])
        for fname in stored_order:
            field = self._fields[fname]
            self.env.compute_field(new_record, field)
        # Propagate to dependents (other records may depend on this one
        # via Many2one traversal, but at create time nothing points at us
        # yet — still notify in case future invariants require it).
        changed = list(column_vals) + list(m2m_vals) + stored_order
        if changed:
            self.env.notify_changed(self._name, [new_id], changed)
        return new_record

    def write(self, vals: dict[str, Any]) -> None:
        if not self._ids:
            return
        column_vals, m2m_vals = self._split_vals(vals)
        if column_vals:
            assigns = ", ".join(f'"{self._fields[f].column}" = %s' for f in column_vals)
            params = [self._fields[f].to_sql_param(v) for f, v in column_vals.items()]
            placeholders = ",".join(["%s"] * len(self._ids))
            sql = (
                f'UPDATE "{self._table}" SET {assigns} '
                f'WHERE "id" IN ({placeholders})'
            )
            self.env.conn.execute(sql, params + list(self._ids))
            for rid in self._ids:
                for fname, value in column_vals.items():
                    self.env.cache.set(
                        self._name, rid, fname,
                        self._fields[fname].to_sql_param(value),
                    )
        if m2m_vals:
            self._apply_m2m(list(self._ids), m2m_vals)
        changed = list(column_vals) + list(m2m_vals)
        if changed:
            self.env.notify_changed(self._name, list(self._ids), changed)

    def unlink(self) -> None:
        if not self._ids:
            return
        placeholders = ",".join(["%s"] * len(self._ids))
        sql = f'DELETE FROM "{self._table}" WHERE "id" IN ({placeholders})'
        self.env.conn.execute(sql, list(self._ids))
        self.env.cache.invalidate(model_name=self._name, ids=list(self._ids))

    # ------ READ ------

    def _read(self, fields: list[str]) -> None:
        """Bulk-load `fields` for self._ids into the cache."""
        if not self._ids:
            return
        fields = [f for f in fields if self._fields[f].is_stored]
        if not fields:
            return
        missing_ids = [
            rid
            for rid in self._ids
            if any(not self.env.cache.contains(self._name, rid, f) for f in fields)
        ]
        if not missing_ids:
            return
        # Select by column, but cache under attr name.
        select_cols = ['"id"'] + [f'"{self._fields[f].column}"' for f in fields]
        placeholders = ",".join(["%s"] * len(missing_ids))
        sql = (
            f'SELECT {", ".join(select_cols)} FROM "{self._table}" '
            f'WHERE "id" IN ({placeholders})'
        )
        rows = self.env.conn.execute(sql, missing_ids).fetchall()
        for row in rows:
            rid = row[0]
            for i, fname in enumerate(fields, start=1):
                self.env.cache.set(self._name, rid, fname, row[i])

    def read(self, fields: list[str] | None = None) -> list[dict[str, Any]]:
        # Default: stored fields only. Non-stored (One2many, future computes)
        # must be accessed via the descriptor explicitly.
        if fields is None:
            fields = [f for f, fld in self._fields.items() if fld.is_stored]
        self._read([f for f in fields if self._fields[f].is_stored])
        out = []
        for rid in self._ids:
            record = {"id": rid}
            for fname in fields:
                field = self._fields[fname]
                if field.is_stored:
                    record[fname] = field.to_python(
                        self.env.cache.get(self._name, rid, fname)
                    )
                else:
                    record[fname] = field.__get__(
                        self.__class__(self.env, (rid,)), self.__class__
                    )
            out.append(record)
        return out

    # ------ SEARCH ------

    def search(
        self,
        domain: list[tuple] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> "BaseModel":
        where, params, joins = domain_to_sql(domain, self.__class__)
        base = f'"{self._table}"'
        sql = f'SELECT {base}."id" FROM {base}{joins} WHERE {where}'
        if order:
            sql += f" ORDER BY {order}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"
        rows = self.env.conn.execute(sql, params).fetchall()
        return self.__class__(self.env, tuple(r[0] for r in rows))

    def search_count(self, domain: list[tuple] | None = None) -> int:
        where, params, joins = domain_to_sql(domain, self.__class__)
        base = f'"{self._table}"'
        sql = f'SELECT COUNT(*) FROM {base}{joins} WHERE {where}'
        return self.env.conn.execute(sql, params).fetchone()[0]
