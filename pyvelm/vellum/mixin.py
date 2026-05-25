"""Opt-in Vellum mixin — query builder + collection helpers on recordsets."""
from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator

from pyvelm.env import Environment

from ._metadata import install_vellum_metadata
from ._subclass import _detect_field_method_collisions
from .attribute import apply_mutators, read_accessor
from .fillable import (
    apply_vellum_mass_assignment_defaults,
    filter_mass_assignment,
    validate_mass_assignment_config,
)
from .collection import filter_recordset, where_recordset, wrap
from .events import fire as fire_vellum_event
from .query import QueryBuilder
from .relations import BelongsTo, BelongsToMany, HasMany, HasOne
def finalize_vellum_model(cls) -> None:
    """Post-metaclass setup for Vellum models (timestamps, mass assignment, metadata)."""
    if Vellum not in getattr(cls, "__mro__", ()) or not getattr(cls, "_name", None):
        return
    if getattr(cls, "_vellum_finalized", False):
        return
    _detect_field_method_collisions(cls)
    validate_mass_assignment_config(cls)
    from pyvelm.timestamps import install_timestamps

    install_timestamps(cls)
    apply_vellum_mass_assignment_defaults(cls)
    install_vellum_metadata(cls)
    cls._vellum_finalized = True


class Vellum:
    """Mixin for recordset collection helpers (``pluck``, in-memory ``where``, …).

    List **before** ``BaseModel`` so Vellum overrides CRUD (Python MRO)::

        class Post(Vellum, BaseModel):
            _name = "blog.post"

    Inherits framework automatic ``created_at`` / ``updated_at`` from
    :class:`~pyvelm.model.BaseModel` (``_timestamps = True`` by default).

    For SQL queries at runtime, prefer ``env.query("blog.post")`` so you
    always use the registry class after ``_inherit`` merges. ``Post.query(env)``
    is fine in the defining module (tests, type-checked code).
    """

    _timestamps = True

    def __getattr__(self, name: str):
        accessors = getattr(self.__class__, "_vellum_accessors", None) or {}
        if name not in accessors:
            raise AttributeError(name)
        return read_accessor(self, name, accessors)

    def create(self, vals: dict[str, Any]):
        cls = self.__class__
        vals = filter_mass_assignment(cls, dict(vals))
        vals = apply_mutators(cls, self.env, vals)
        empty = cls(self.env, ())
        fire_vellum_event(cls, "creating", empty, vals=vals)
        fire_vellum_event(cls, "saving", empty, vals=vals)
        rec = super().create(vals)
        fire_vellum_event(cls, "created", rec)
        fire_vellum_event(cls, "saved", rec)
        return rec

    def write(self, vals: dict[str, Any]) -> None:
        if not self._ids:
            return
        cls = self.__class__
        vals = filter_mass_assignment(cls, dict(vals))
        vals = apply_mutators(cls, self.env, vals)
        fire_vellum_event(cls, "updating", self)
        fire_vellum_event(cls, "saving", self)
        super().write(vals)
        fire_vellum_event(cls, "updated", self)
        fire_vellum_event(cls, "saved", self)

    def unlink(self) -> None:
        if not self._ids:
            return
        cls = self.__class__
        fire_vellum_event(cls, "deleting", self)
        super().unlink()
        fire_vellum_event(cls, "deleted", cls(self.env, ()))

    @classmethod
    def query(cls, env: Environment) -> QueryBuilder:
        """Build a query for this class. See :meth:`Environment.query` for apps."""
        return QueryBuilder(model_cls=cls, env=env)

    # --- collection helpers (in-memory layer) ---------------------------

    def pluck(self, field: str) -> list[Any]:
        if not self._ids:
            return []
        rows = self.read([field])
        return [row[field] for row in rows]

    def first(self):
        if not self._ids:
            return self.__class__(self.env, ())
        return self.__class__(self.env, (self._ids[0],))

    def last(self):
        if not self._ids:
            return self.__class__(self.env, ())
        return self.__class__(self.env, (self._ids[-1],))

    def contains(self, other) -> bool:
        if not isinstance(other, self.__class__) or other._name != self._name:
            return False
        if not other._ids:
            return True
        return set(other._ids).issubset(set(self._ids))

    def where(self, field: str, op: str | Any = None, value: Any = None):
        return where_recordset(self, field, op, value)

    def find(self, record_id: int):
        if record_id in self._ids:
            return self.__class__(self.env, (record_id,))
        return self.__class__(self.env, ())

    def map(self, fn: Callable):
        return [fn(rec) for rec in self]

    def filter(self, fn: Callable):
        return filter_recordset(self, fn)

    def each(self, fn: Callable) -> None:
        for rec in self:
            fn(rec)

    def chunk(self, size: int) -> Iterator:
        if size < 1:
            raise ValueError("chunk size must be >= 1")
        ids = list(self._ids)
        cls = self.__class__
        for i in range(0, len(ids), size):
            yield cls(self.env, tuple(ids[i : i + size]))

    def to_list(self) -> list[dict[str, Any]]:
        if not self._ids:
            return []
        return self.read()

    def fresh(self):
        """Re-query the same ids from the database (drops stale cache reads)."""
        if not self._ids:
            return self
        return self.__class__(self.env, ()).search(
            [("id", "in", list(self._ids))]
        )

    @classmethod
    def wrap(cls, rs):
        """Optional adapter — returns the recordset as-is when already a Vellum model."""
        return wrap(rs)

    # --- relation helpers (Slice B) -------------------------------------

    def belongs_to(self, comodel_name: str, foreign_key: str) -> BelongsTo:
        return BelongsTo.for_parent(self, comodel_name, foreign_key)

    def has_many(self, comodel_name: str, inverse_name: str) -> HasMany:
        return HasMany.for_parent(self, comodel_name, inverse_name)

    def has_one(self, comodel_name: str, inverse_name: str) -> HasOne:
        return HasOne.for_parent(self, comodel_name, inverse_name)

    def belongs_to_many(self, comodel_name: str, field_name: str) -> BelongsToMany:
        return BelongsToMany.for_parent(self, comodel_name, field_name)

    def count_of(self, field_name: str) -> int:
        """Count from a prior ``with_count('field_name')`` on the query that loaded this row."""
        self.ensure_one()
        counts = getattr(self, "_vellum_counts", None) or {}
        per_field = counts.get(field_name)
        if per_field is None:
            raise ValueError(
                f"No with_count({field_name!r}) data on this recordset — "
                f"chain .with_count(...) before .get()."
            )
        return int(per_field.get(self.id, 0))

    def fill(self, vals: dict[str, Any]) -> None:
        """Mass-assignment-safe partial update (``write`` after filtering)."""
        self.write(vals)
