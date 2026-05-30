from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from .domain import domain_to_sql
from .fields import Char, Field, Integer, Many2one, finalize_related_field
from .registry import active_registry
from .timestamps import (
    apply_timestamp_vals,
    inject_timestamp_fields,
    is_system_timestamp_field,
    resolve_timestamps_enabled,
)


def _rec_name_field(cls) -> str | None:
    """Return the Char/Text (etc.) field used for the default display_name."""
    raw = getattr(cls, "_rec_name", "name")
    if not raw:
        return None
    name = str(raw)
    return name if name in cls._fields else None


def _display_name_depends(cls) -> tuple[str, ...]:
    rec = _rec_name_field(cls)
    return (rec,) if rec else ("id",)


def _inject_id(model_name: str, fields: dict[str, Field]) -> None:
    """Primary key — always present in ``_fields`` and dependency paths."""
    if "id" in fields:
        return
    field = Integer(string="ID", readonly=True, required=True)
    field.bind(model_name, "id")
    fields["id"] = field


def _inject_display_name(model_name: str, fields: dict[str, Field]) -> None:
    if "display_name" in fields:
        return
    field = Char(compute="_compute_display_name", string="Display Name")
    field.bind(model_name, "display_name")
    fields["display_name"] = field


def _install_auto_fields(
    cls, namespace: dict, fields: dict[str, Field]
) -> None:
    """Expose metaclass-injected fields as class descriptors."""
    for fname in ("id", "display_name"):
        if fname in fields and fname not in namespace:
            setattr(cls, fname, fields[fname])


def _bind_compute_fields(
    cls, fields: dict[str, Field], namespace: dict
) -> None:
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
            if fname == "display_name" and field.compute == "_compute_display_name":
                deps = _display_name_depends(cls)
            else:
                raise ValueError(
                    f"{cls._name}.{fname}: compute method "
                    f"{field.compute!r} must be decorated with @depends(...)"
                )
        field.depends_on = tuple(deps)


class MetaModel(type):
    def __new__(mcs, name, bases, namespace):
        _inherit = namespace.get("_inherit")
        _name_val = namespace.get("_name")

        # --- _inherit: extend an existing model class ---
        if _inherit and not _name_val:
            return mcs._build_extension(name, bases, namespace, _inherit)

        cls = super().__new__(mcs, name, bases, namespace)

        # Collect fields from this class and its bases.
        fields: dict[str, Field] = {}
        for base in reversed(bases):
            fields.update(getattr(base, "_fields", {}))
        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, Field):
                attr_value.bind(namespace.get("_name") or "", attr_name)
                fields[attr_name] = attr_value

        # Auto-inject company_id for company-scoped models.
        if namespace.get("_company_scoped") and "company_id" not in fields:
            co_field = Many2one("res.company")
            co_field.bind(namespace.get("_name") or "", "company_id")
            fields["company_id"] = co_field

        if _name_val:
            _inject_id(_name_val, fields)
            _inject_display_name(_name_val, fields)
            if resolve_timestamps_enabled(namespace, bases):
                inject_timestamp_fields(
                    _name_val,
                    fields,
                    created_at=namespace.get("_CREATED_AT", "created_at"),
                    updated_at=namespace.get("_UPDATED_AT", "updated_at"),
                )

        cls._fields = fields
        for f in fields.values():
            finalize_related_field(cls, f)

        # Defer table name and registry binding to subclasses with _name.
        if _name_val:
            cls._table = namespace.get("_table") or _name_val.replace(".", "_")
            for f in fields.values():
                f.model_name = cls._name
            _install_auto_fields(cls, namespace, fields)
            if resolve_timestamps_enabled(namespace, bases):
                from .timestamps import install_timestamps

                install_timestamps(cls)
            _bind_compute_fields(cls, fields, namespace)
            active_registry().register(cls)
        return cls

    @classmethod
    def _build_extension(mcs, ext_name: str, bases, namespace: dict, inherit_name: str):
        """Handle `_inherit = "some.model"` without a new `_name`.

        Creates a new Python class that subclasses the existing registered
        model class, merges in additional fields, and replaces the registry
        entry so env["some.model"] returns the extended class going forward.
        Python MRO gives `super()` access to the original methods.
        """
        reg = active_registry()
        if inherit_name not in reg:
            raise ValueError(
                f"_inherit = {inherit_name!r}: model not found in registry. "
                f"Ensure its module is loaded before this extension."
            )
        existing = reg[inherit_name]

        # Build bases: replace BaseModel (or any MetaModel base without _name)
        # with the existing model class so Python MRO chains correctly.
        new_bases: tuple = tuple(
            existing if (b is existing or (
                isinstance(b, MetaModel) and not getattr(b, "_name", None)
            )) else b
            for b in bases
        )
        if existing not in new_bases:
            new_bases = (existing,)

        # Strip _inherit so the normal metaclass path treats this like a
        # regular subclass once the class object is built.
        clean_ns = {k: v for k, v in namespace.items() if k != "_inherit"}
        clean_ns["_name"] = existing._name
        clean_ns["_table"] = existing._table

        cls = super().__new__(mcs, ext_name, new_bases, clean_ns)

        # Shallow-copy Field descriptors so rebinding compute deps on the
        # extended class cannot mutate the parent module's class definition
        # (cached imports would then leak deps into later registries).
        merged: dict[str, Field] = {}
        for attr_name, field in existing._fields.items():
            cloned = copy(field)
            cloned.bind(existing._name, attr_name)
            merged[attr_name] = cloned
        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, Field):
                attr_value.bind(existing._name, attr_name)
                merged[attr_name] = attr_value
        _inject_id(existing._name, merged)
        _inject_display_name(existing._name, merged)
        if resolve_timestamps_enabled(namespace, bases):
            inject_timestamp_fields(
                existing._name,
                merged,
                created_at=namespace.get(
                    "_CREATED_AT", getattr(existing, "_CREATED_AT", "created_at")
                ),
                updated_at=namespace.get(
                    "_UPDATED_AT", getattr(existing, "_UPDATED_AT", "updated_at")
                ),
            )
        cls._fields = merged
        for f in merged.values():
            finalize_related_field(cls, f)

        # Update model_name on all fields (some may have been rebound from
        # the parent with the wrong model_name if the parent was itself an
        # extension).
        for f in merged.values():
            f.model_name = existing._name

        _install_auto_fields(cls, namespace, merged)
        if resolve_timestamps_enabled(namespace, bases):
            from .timestamps import install_timestamps

            install_timestamps(cls)
        _bind_compute_fields(cls, merged, namespace)

        # Replace registry entry with the extended class.
        reg.register(cls, module_name=reg._model_module.get(existing._name))
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
    _company_scoped: bool = False  # set True to auto-inject company_id
    _timestamps: bool = True  # auto ``created_at`` / ``updated_at`` on CRUD
    _CREATED_AT: str = "created_at"
    _UPDATED_AT: str = "updated_at"
    # Field whose value feeds the default ``display_name`` compute (when
    # the model does not override ``_compute_display_name``). Defaults to
    # ``"name"``; set to another field name, or ``False`` to use only id.
    _rec_name: str | bool = "name"

    def _compute_display_name(self) -> None:
        """Default display label: ``_rec_name`` value, else ``model #id``."""
        rec_field = _rec_name_field(type(self))
        for record in self:
            label = None
            if rec_field:
                val = getattr(record, rec_field)
                if val not in (None, ""):
                    label = str(val)
            if label is None:
                label = f"{record._name} #{record.id}"
            record.display_name = label

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

    def sudo(self, flag: bool = True) -> "BaseModel":
        """Return this recordset bound to a sudo env (see ``Environment.sudo``).

        ``records.sudo()`` bypasses access checks and record rules for
        operations on the returned recordset; the original is untouched.
        ``records.sudo(False)`` returns an access-enforced recordset.

            partner.sudo().write({"credit_limit": 0})
        """
        return self.__class__(self.env.sudo(flag), self._ids)

    # ------ DDL ------

    @classmethod
    def _setup_table(cls, conn) -> None:
        # Phase 1: create the table if it doesn't exist (includes all
        # currently-known columns with their constraints).
        cols = ['"id" SERIAL PRIMARY KEY']
        for f in cls._fields.values():
            if not f.is_stored or f.name == "id":
                continue
            cols.append(f.column_ddl())
        conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{cls._table}" ({", ".join(cols)})'
        )
        # Phase 2: add any columns that are missing (idempotent).
        # Used when a module extends an existing model via _inherit at
        # install time.  Existing columns are a no-op; new ones are added
        # as nullable so pre-existing rows aren't rejected.
        for f in cls._fields.values():
            if not f.is_stored or f.name == "id":
                continue
            conn.execute(
                f'ALTER TABLE "{cls._table}" '
                f'ADD COLUMN IF NOT EXISTS "{f.column}" {f.sql_type}'
            )

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
            if f.related or not f.is_stored or not f.column:
                continue
            if f.comodel_name not in registry:
                raise ValueError(
                    f"{cls._name}.{f.name} references unknown model {f.comodel_name!r}"
                )
            target = registry[f.comodel_name]
            # Cross-module ``_inherit`` adds fields whose target table
            # belongs to a not-yet-installed module. The extending
            # module's own ``_setup_module_schema`` runs FK setup on
            # this class again once its tables exist (via
            # ``_model_extensions``), so we defer the constraint until
            # then rather than failing the base install with
            # ``UndefinedTable``. The DROP-IF-EXISTS below is also
            # idempotent on the second pass.
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = %s",
                [target._table],
            ).fetchone()
            if row is None:
                continue
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

    def _split_vals(self, vals: dict[str, Any]) -> tuple[dict, dict, dict]:
        """Split vals into (column_vals, m2m_vals, related_vals)."""
        from .fields import Many2many

        column_vals: dict[str, Any] = {}
        m2m_vals: dict[str, Any] = {}
        related_vals: dict[str, Any] = {}
        for fname, value in vals.items():
            if fname not in self._fields:
                raise ValueError(f"Unknown field {fname!r} on {self._name}")
            field = self._fields[fname]
            if field.readonly:
                if not is_system_timestamp_field(self.__class__, fname):
                    raise ValueError(
                        f"{self._name}.{fname} is readonly and cannot be written."
                    )
            if field.related:
                related_vals[fname] = value
            elif isinstance(field, Many2many):
                m2m_vals[fname] = value
            elif field.is_stored:
                column_vals[fname] = value
            elif field.compute:
                raise ValueError(
                    f"{self._name}.{fname} is computed; "
                    f"assign through its dependencies instead."
                )
            else:
                raise ValueError(
                    f"{self._name}.{fname} is not stored; "
                    f"cannot be written directly"
                )
        return column_vals, m2m_vals, related_vals

    def _apply_related_vals(self, related_vals: dict[str, Any]) -> None:
        """Write related fields by delegating to the leaf on each record."""
        if not related_vals or not self._ids:
            return
        for rid in self._ids:
            rec = self.__class__(self.env, (rid,))
            for fname, value in related_vals.items():
                setattr(rec, fname, value)

    def _snapshot_many2one_columns(
        self, field_names: list[str]
    ) -> dict[str, dict[int, Any]]:
        """Read current FK values for *field_names* on ``self._ids`` (cache or SQL)."""
        from .fields import Many2one

        out: dict[str, dict[int, Any]] = {}
        if not self._ids:
            return out
        for fname in field_names:
            field = self._fields.get(fname)
            if not isinstance(field, Many2one):
                continue
            per_rid: dict[int, Any] = {}
            missing: list[int] = []
            for rid in self._ids:
                if self.env.cache.contains(self._name, rid, fname):
                    per_rid[rid] = self.env.cache.get(self._name, rid, fname)
                else:
                    missing.append(rid)
            if missing:
                col = field.column
                placeholders = ",".join(["%s"] * len(missing))
                rows = self.env.conn.execute(
                    f'SELECT "id", "{col}" FROM "{self._table}" '
                    f'WHERE "id" IN ({placeholders})',
                    missing,
                ).fetchall()
                for rid, raw in rows:
                    per_rid[rid] = raw
            out[fname] = per_rid
        return out

    def _snapshot_m2m_peers(self, fname: str) -> set[int]:
        """Distinct comodel ids linked via a Many2many before a write/unlink."""
        from .fields import Many2many

        field = self._fields.get(fname)
        if not isinstance(field, Many2many) or not self._ids:
            return set()
        relation, col1, col2, _, _ = field.resolve_spec(
            type(self), self.env.registry
        )
        placeholders = ",".join(["%s"] * len(self._ids))
        rows = self.env.conn.execute(
            f'SELECT DISTINCT "{col2}" FROM "{relation}" '
            f'WHERE "{col1}" IN ({placeholders})',
            list(self._ids),
        ).fetchall()
        return {int(r[0]) for r in rows}

    def _invalidate_symmetric_m2m(self, fname: str, peer_ids: set[int]) -> None:
        """Invalidate the other side of a shared junction table."""
        from .fields import Many2many

        if not peer_ids:
            return
        field = self._fields.get(fname)
        if not isinstance(field, Many2many):
            return
        relation, col1, col2, _, _ = field.resolve_spec(
            type(self), self.env.registry
        )
        for model_name, other_fname, other_col1, other_col2 in (
            self.env.registry._m2m_relation_index.get(relation, [])
        ):
            if model_name == self._name and other_fname == fname:
                continue
            # peer_ids are always on the comodel side (col2 of this field).
            if other_col1 == col2 and other_col2 == col1:
                self.env.cache.invalidate(
                    model_name=model_name,
                    ids=list(peer_ids),
                    fields=[other_fname],
                )

    def _invalidate_relational_caches(
        self,
        column_vals: dict[str, Any],
        m2m_vals: dict[str, Any],
        *,
        before_m2o: dict[str, dict[int, Any]] | None = None,
    ) -> None:
        """Drop cached One2many/Many2many tuples affected by this mutation."""
        from collections import defaultdict

        from .fields import Many2one

        inv_index = self.env.registry._o2m_inverse_index
        to_clear: dict[tuple[str, str], set[int]] = defaultdict(set)

        if before_m2o:
            for fname, old_map in before_m2o.items():
                for parent_model, o2m_fname in inv_index.get(
                    (self._name, fname), []
                ):
                    for old_pid in old_map.values():
                        if old_pid is not None:
                            to_clear[(parent_model, o2m_fname)].add(int(old_pid))

        if column_vals:
            for fname, new_val in column_vals.items():
                field = self._fields.get(fname)
                if isinstance(field, Many2one):
                    new_pid = field.to_sql_param(new_val)
                    for parent_model, o2m_fname in inv_index.get(
                        (self._name, fname), []
                    ):
                        if new_pid is not None:
                            to_clear[(parent_model, o2m_fname)].add(int(new_pid))

        for fname in m2m_vals:
            to_clear[(self._name, fname)].update(self._ids)

        for (parent_model, field_name), parent_ids in to_clear.items():
            if parent_ids:
                self.env.cache.invalidate(
                    model_name=parent_model,
                    ids=list(parent_ids),
                    fields=[field_name],
                )

    def _invalidate_m2o_referrers(self) -> None:
        """Drop stale Many2one (and related O2M) cache on rows pointing at us."""
        referrers = self.env.registry._m2o_referrers_index.get(self._name, [])
        if not referrers or not self._ids:
            return
        deleted = list(self._ids)
        placeholders = ",".join(["%s"] * len(deleted))
        for ref_model, ref_fname, ondelete in referrers:
            ref_cls = self.env.registry[ref_model]
            col = ref_cls._fields[ref_fname].column
            rows = self.env.conn.execute(
                f'SELECT "id" FROM "{ref_cls._table}" '
                f'WHERE "{col}" IN ({placeholders})',
                deleted,
            ).fetchall()
            ref_ids = [int(r[0]) for r in rows]
            if not ref_ids:
                continue
            rs = self.env[ref_model].browse(ref_ids)
            if ondelete == "SET NULL":
                before = rs._snapshot_many2one_columns([ref_fname])
                for rid in ref_ids:
                    self.env.cache.set(ref_model, rid, ref_fname, None)
                rs._invalidate_relational_caches(
                    {ref_fname: None}, {}, before_m2o=before
                )
            elif ondelete == "CASCADE":
                rs._invalidate_before_unlink()
                self.env.cache.invalidate(model_name=ref_model, ids=ref_ids)

    def _invalidate_before_unlink(self) -> None:
        """Invalidate O2M/M2M caches that will change when these rows disappear."""
        from .fields import Many2many, Many2one

        inv_index = self.env.registry._o2m_inverse_index
        m2o_fields = [
            fname
            for fname, field in self._fields.items()
            if isinstance(field, Many2one) and (self._name, fname) in inv_index
        ]
        if m2o_fields:
            snap = self._snapshot_many2one_columns(m2o_fields)
            self._invalidate_relational_caches({}, {}, before_m2o=snap)
        m2m_fields = [
            fname
            for fname, field in self._fields.items()
            if isinstance(field, Many2many)
        ]
        if m2m_fields and self._ids:
            for fname in m2m_fields:
                peers = self._snapshot_m2m_peers(fname)
                self.env.cache.invalidate(
                    model_name=self._name,
                    ids=list(self._ids),
                    fields=[fname],
                )
                self._invalidate_symmetric_m2m(fname, peers)

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
        self.env.check_access(self._name, "create")
        vals = apply_timestamp_vals(self.__class__, vals, updating=False)
        column_vals, m2m_vals, related_vals = self._split_vals(vals)
        # Auto-inject company_id from env for company-scoped models when
        # the caller hasn't provided one explicitly.
        if (
            self.__class__._company_scoped
            and "company_id" not in column_vals
            and self.env.company_id is not None
        ):
            column_vals["company_id"] = self.env.company_id
        # Apply Field.default for any stored field the caller didn't set.
        # Computed fields skip this — they fill themselves via the topo
        # walk below. Non-stored relational defaults aren't applicable.
        for fname, field in self._fields.items():
            if fname in column_vals or fname in m2m_vals:
                continue
            if not field.is_stored or field.compute:
                continue
            if field.default is None:
                continue
            column_vals[fname] = field.default
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
        self._invalidate_relational_caches(column_vals, m2m_vals)
        for fname, value in m2m_vals.items():
            peers = set(self._fields[fname].normalize_ids(value))
            new_record._invalidate_symmetric_m2m(fname, peers)
        if related_vals:
            new_record._apply_related_vals(related_vals)
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
        # Fire on_create automation rules after the record is fully set up.
        from .automation import AutomationEngine
        AutomationEngine.fire(self.env, self._name, "on_create", new_record)
        from .workflow.runtime import maybe_auto_start_workflow
        maybe_auto_start_workflow(self.env, new_record)
        return new_record

    def write(self, vals: dict[str, Any]) -> None:
        if not self._ids:
            return
        self.env.check_access(self._name, "write")
        vals = apply_timestamp_vals(self.__class__, vals, updating=True)
        column_vals, m2m_vals, related_vals = self._split_vals(vals)
        inv_index = self.env.registry._o2m_inverse_index
        m2o_to_snap = [
            fname
            for fname in column_vals
            if (self._name, fname) in inv_index
        ]
        before_m2o = (
            self._snapshot_many2one_columns(m2o_to_snap) if m2o_to_snap else None
        )
        before_m2m_peers = {
            fname: self._snapshot_m2m_peers(fname) for fname in m2m_vals
        }
        from . import mail_tracking

        tracked_cols = mail_tracking.tracked_field_names(
            self.__class__, column_vals
        )
        tracked_m2m = mail_tracking.tracked_field_names(
            self.__class__, m2m_vals
        )
        tracking_before = (
            mail_tracking.snapshot_before_write(
                self, tracked_cols, tracked_m2m
            )
            if (tracked_cols or tracked_m2m)
            and mail_tracking.model_has_mail_thread(self.__class__)
            else None
        )
        if related_vals:
            self._apply_related_vals(related_vals)
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
        self._invalidate_relational_caches(
            column_vals, m2m_vals, before_m2o=before_m2o
        )
        for fname, value in m2m_vals.items():
            field = self._fields[fname]
            new_peers = set(field.normalize_ids(value))
            affected = before_m2m_peers.get(fname, set()) | new_peers
            self._invalidate_symmetric_m2m(fname, affected)
        if tracking_before is not None:
            mail_tracking.post_write_tracking(
                self, column_vals, m2m_vals, tracking_before
            )
        changed = list(column_vals) + list(m2m_vals)
        if changed:
            self.env.notify_changed(self._name, list(self._ids), changed)
        # Fire on_write automation rules after the write is committed to cache.
        from .automation import AutomationEngine
        AutomationEngine.fire(self.env, self._name, "on_write", self)

    def unlink(self) -> None:
        if not self._ids:
            return
        self.env.check_access(self._name, "unlink")
        self._invalidate_before_unlink()
        self._invalidate_m2o_referrers()
        # Fire on_unlink automation rules before the records are deleted.
        from .automation import AutomationEngine
        AutomationEngine.fire(self.env, self._name, "on_unlink", self)
        placeholders = ",".join(["%s"] * len(self._ids))
        sql = f'DELETE FROM "{self._table}" WHERE "id" IN ({placeholders})'
        self.env.conn.execute(sql, list(self._ids))
        self.env.cache.invalidate(model_name=self._name, ids=list(self._ids))

    # ------ READ ------

    def _read(self, fields: list[str]) -> None:
        """Bulk-load `fields` for self._ids into the cache."""
        if not self._ids:
            return
        self.env.check_access(self._name, "read")
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
        # must be accessed via the descriptor explicitly. Private fields
        # (``Password`` and friends) are dropped from the default set so
        # bulk reads can't accidentally leak hashes; callers wanting them
        # must pass the field name explicitly.
        if fields is None:
            fields = [
                f for f, fld in self._fields.items()
                if fld.is_stored and not fld.private
            ]
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
        self.env.check_access(self._name, "read")
        # AND every applicable ir.rule's domain into the user's view.
        full_domain = list(domain or [])
        rule_leaves = self.env.collect_record_rules(self._name, "read")
        if rule_leaves:
            full_domain.extend(rule_leaves)
        # Auto-inject company scope when env.company_id is set and the
        # model opted in via `_company_scoped`. Applies to everyone
        # (including superuser) so the company switcher demos
        # consistently — to see every record across companies, use
        # `env.with_company(None)` explicitly. The ACL-bypass path
        # always skips so installer/migration code can see the world.
        if (
            not self.env._acl_bypass
            and self.env.company_id is not None
            and getattr(self.__class__, "_company_scoped", False)
        ):
            full_domain.append(("company_id", "=", self.env.company_id))
        where, params, joins = domain_to_sql(
            full_domain, self.__class__, self.env.registry
        )
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
        self.env.check_access(self._name, "read")
        full_domain = list(domain or [])
        rule_leaves = self.env.collect_record_rules(self._name, "read")
        if rule_leaves:
            full_domain.extend(rule_leaves)
        if (
            not self.env._acl_bypass
            and self.env.company_id is not None
            and getattr(self.__class__, "_company_scoped", False)
        ):
            full_domain.append(("company_id", "=", self.env.company_id))
        where, params, joins = domain_to_sql(
            full_domain, self.__class__, self.env.registry
        )
        base = f'"{self._table}"'
        sql = f'SELECT COUNT(*) FROM {base}{joins} WHERE {where}'
        return self.env.conn.execute(sql, params).fetchone()[0]

    # ---- aggregated reads (read_group) ------------------------------
    #
    # `read_group(domain, groupby, measures)` issues a single SQL GROUP BY
    # against the base table and returns one dict per group. It mirrors
    # `search_count` for ACL / record rules / company scope so the
    # aggregates can never include rows the caller wouldn't see in a
    # plain ``search()``.
    #
    # Grouping
    #     `groupby` is a list of field names. A date/datetime field can
    #     be suffixed with `:day|week|month|quarter|year` to bucket by
    #     ``date_trunc``. Many2one fields group on the FK id; labels
    #     are resolved in a single follow-up read per comodel and
    #     surfaced as ``<spec>__label`` on each result row.
    #
    # Measures
    #     `measures` is a list of strings of the form ``"field"`` or
    #     ``"field:agg"`` where agg ∈ ``sum|avg|min|max|count``. The
    #     default agg for Integer/Float/Monetary is ``sum``; everything
    #     else defaults to ``count``. The special token ``"__count"``
    #     returns ``COUNT(*)``; it's always added automatically when
    #     missing, so consumers can rely on ``row["__count"]`` for the
    #     group's record count.
    #
    # Limits
    #     `limit` / `offset` paginate the group result set (not the
    #     underlying rows). `order` is an opaque SQL fragment that
    #     references the SELECT aliases — for first-iteration use the
    #     caller is expected to know what they're sorting on.
    #
    # Out of scope for now: cube / rollup totals, having clauses,
    # group-by on M2m fields (would need a JOIN through the rel
    # table), and label resolution for non-M2o grouping that wants a
    # human form (e.g. Boolean → "Yes/No" — caller does it client-side).
    def read_group(
        self,
        domain: list[tuple] | None = None,
        groupby: "list[str] | tuple[str, ...] | str" = (),
        measures: "list[str] | str | None" = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        from .fields import Date, Datetime, Float, Integer, Many2one

        self.env.check_access(self._name, "read")
        full_domain = list(domain or [])
        rule_leaves = self.env.collect_record_rules(self._name, "read")
        if rule_leaves:
            full_domain.extend(rule_leaves)
        if (
            not self.env._acl_bypass
            and self.env.company_id is not None
            and getattr(self.__class__, "_company_scoped", False)
        ):
            full_domain.append(("company_id", "=", self.env.company_id))

        if isinstance(groupby, str):
            groupby = [groupby] if groupby else []
        else:
            groupby = list(groupby or [])
        if isinstance(measures, str):
            measures = [measures]
        measures = list(measures or [])

        cls = self.__class__
        base = f'"{self._table}"'
        _VALID_TRUNCS = ("day", "week", "month", "quarter", "year")
        _VALID_AGGS = ("sum", "avg", "min", "max", "count")

        select_parts: list[str] = []
        group_sql_parts: list[str] = []
        # group_keys: list of (output_key, field_name, trunc_or_None,
        #                     is_m2o, comodel_name_or_None)
        group_keys: list[tuple[str, str, str | None, bool, str | None]] = []
        for spec in groupby:
            if ":" in spec:
                fname, trunc = spec.split(":", 1)
            else:
                fname, trunc = spec, None
            if fname not in cls._fields:
                raise ValueError(
                    f"read_group: unknown groupby field {fname!r} on {self._name}"
                )
            field = cls._fields[fname]
            if not field.is_stored:
                raise ValueError(
                    f"read_group: cannot group by non-stored field {fname!r}"
                )
            col_sql = f'{base}."{field.column}"'
            if trunc:
                if not isinstance(field, (Date, Datetime)):
                    raise ValueError(
                        f"read_group: trunc {trunc!r} only valid on Date / "
                        f"Datetime fields, not {field.__class__.__name__}"
                    )
                if trunc not in _VALID_TRUNCS:
                    raise ValueError(
                        f"read_group: bad trunc {trunc!r}, "
                        f"expected one of {_VALID_TRUNCS}"
                    )
                expr = f"date_trunc('{trunc}', {col_sql})"
                # The output key is the original spec so callers can
                # round-trip it (and the front-end can index by it).
                alias = f"g_{len(group_keys)}"
                select_parts.append(f'{expr} AS "{alias}"')
                group_sql_parts.append(expr)
                group_keys.append((spec, fname, trunc, False, None))
            else:
                alias = f"g_{len(group_keys)}"
                select_parts.append(f'{col_sql} AS "{alias}"')
                group_sql_parts.append(col_sql)
                is_m2o = isinstance(field, Many2one)
                comodel = field.comodel_name if is_m2o else None
                group_keys.append((spec, fname, None, is_m2o, comodel))

        # measure_keys: list of (output_key, agg, field_name_or_None)
        measure_keys: list[tuple[str, str, str | None]] = []
        seen_count = False
        for spec in measures:
            if spec == "__count":
                if seen_count:
                    continue
                seen_count = True
                select_parts.append('COUNT(*) AS "__count"')
                measure_keys.append(("__count", "count_star", None))
                continue
            if ":" in spec:
                mfield, agg = spec.split(":", 1)
            else:
                mfield, agg = spec, None
            if mfield not in cls._fields:
                raise ValueError(
                    f"read_group: unknown measure field {mfield!r} on {self._name}"
                )
            mf = cls._fields[mfield]
            if not mf.is_stored:
                raise ValueError(
                    f"read_group: cannot aggregate non-stored field {mfield!r}"
                )
            if agg is None:
                agg = "sum" if isinstance(mf, (Integer, Float)) else "count"
            if agg not in _VALID_AGGS:
                raise ValueError(
                    f"read_group: bad agg {agg!r} for {mfield!r}, "
                    f"expected one of {_VALID_AGGS}"
                )
            out_key = f"{mfield}:{agg}"
            alias = f"m_{len(measure_keys)}"
            col = f'{base}."{mf.column}"'
            select_parts.append(f'{agg.upper()}({col}) AS "{alias}"')
            measure_keys.append((out_key, agg, mfield))
        if not seen_count:
            # `__count` is always present so consumers can rely on it
            # without conditional logic — matches Odoo's read_group.
            select_parts.append('COUNT(*) AS "__count"')
            measure_keys.append(("__count", "count_star", None))

        where, params, joins = domain_to_sql(
            full_domain, cls, self.env.registry
        )
        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {base}{joins} WHERE {where}"
        )
        if group_sql_parts:
            sql += " GROUP BY " + ", ".join(group_sql_parts)
        if order:
            sql += f" ORDER BY {order}"
        elif group_sql_parts:
            # Default: stable order on the group keys themselves.
            sql += " ORDER BY " + ", ".join(group_sql_parts)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"

        cur = self.env.conn.execute(sql, params)
        # We aliased every output column and unpack by position below
        # — group columns first, then measures — so the SELECT order
        # is the contract. ``cur.description`` isn't consulted to
        # stay resilient if the driver ever exposes extra metadata.
        raw_rows = cur.fetchall()
        rows: list[dict[str, Any]] = []
        # Indexes into col_names — group columns first, then measures,
        # then the trailing __count if present.
        n_groups = len(group_keys)
        for raw in raw_rows:
            d: dict[str, Any] = {}
            for i, (out_key, *_rest) in enumerate(group_keys):
                d[out_key] = raw[i]
            for j, (out_key, *_rest) in enumerate(measure_keys):
                d[out_key] = raw[n_groups + j]
            rows.append(d)

        # Resolve labels for Many2one groupbys in a single follow-up
        # query per comodel — keeps the chart / pivot renderers from
        # having to do an N+1 walk.
        for out_key, _fname, _trunc, is_m2o, comodel in group_keys:
            if not is_m2o or comodel is None:
                continue
            ids = {r[out_key] for r in rows if r[out_key] is not None}
            if not ids:
                continue
            labels: dict[int, str] = {}
            CoModel = self.env[comodel]
            for rec in CoModel.browse(tuple(ids)):
                for attr in ("display_name", "name"):
                    if attr in rec._fields:
                        labels[rec.id] = str(getattr(rec, attr) or rec.id)
                        break
                else:
                    labels[rec.id] = str(rec.id)
            label_key = f"{out_key}__label"
            for r in rows:
                rid = r[out_key]
                r[label_key] = labels.get(rid) if rid is not None else None

        return rows
