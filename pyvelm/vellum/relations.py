"""Method-based relations — thin QueryBuilder wrappers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyvelm.env import Environment
from pyvelm.fields import Many2many, Many2one, One2many

from .query import QueryBuilder


def _empty_domain() -> tuple[tuple[str, str, Any], ...]:
    return (("id", "in", []),)


@dataclass(frozen=True)
class Relation:
    """Queryable relation bound to a parent recordset."""

    env: Environment
    parent: object  # BaseModel recordset
    comodel_name: str
    _qb: QueryBuilder

    @property
    def model_cls(self):
        return self._qb.model_cls

    def _wrap(self, qb: QueryBuilder) -> Relation:
        return Relation(
            env=self.env,
            parent=self.parent,
            comodel_name=self.comodel_name,
            _qb=qb,
        )

    def where(self, field: str, op=None, value=None) -> Relation:
        return self._wrap(self._qb.where(field, op, value))

    def where_in(self, field: str, values) -> Relation:
        return self._wrap(self._qb.where_in(field, values))

    def where_not_in(self, field: str, values) -> Relation:
        return self._wrap(self._qb.where_not_in(field, values))

    def where_like(self, field: str, pattern: str) -> Relation:
        return self._wrap(self._qb.where_like(field, pattern))

    def where_ilike(self, field: str, pattern: str) -> Relation:
        return self._wrap(self._qb.where_ilike(field, pattern))

    def where_null(self, field: str) -> Relation:
        return self._wrap(self._qb.where_null(field))

    def where_not_null(self, field: str) -> Relation:
        return self._wrap(self._qb.where_not_null(field))

    def where_between(self, field: str, low, high) -> Relation:
        return self._wrap(self._qb.where_between(field, low, high))

    def where_any(self, *conditions) -> Relation:
        return self._wrap(self._qb.where_any(*conditions))

    def order_by(self, field: str, direction: str = "asc") -> Relation:
        return self._wrap(self._qb.order_by(field, direction))

    def latest(self, field: str = "id") -> Relation:
        return self._wrap(self._qb.latest(field))

    def oldest(self, field: str = "id") -> Relation:
        return self._wrap(self._qb.oldest(field))

    def limit(self, n: int) -> Relation:
        return self._wrap(self._qb.limit(n))

    def offset(self, n: int) -> Relation:
        return self._wrap(self._qb.offset(n))

    def get(self):
        return self._qb.get()

    def first(self):
        return self._qb.first()

    def count(self) -> int:
        return self._qb.count()

    def exists(self) -> bool:
        return self._qb.exists()

    def pluck(self, field: str):
        return self._qb.pluck(field)


@dataclass(frozen=True)
class BelongsTo(Relation):
    """Many2one-style relation from parent FK column to comodel."""

    foreign_key: str

    @classmethod
    def for_parent(cls, parent, comodel_name: str, foreign_key: str) -> BelongsTo:
        parent.ensure_one()
        env = parent.env
        comodel_cls = env.registry[comodel_name]
        fk_field = parent._fields.get(foreign_key)
        if not isinstance(fk_field, Many2one):
            raise ValueError(
                f"{parent._name}.{foreign_key} must be a Many2one for belongs_to()"
            )
        rid = parent._ids[0]
        if not env.cache.contains(parent._name, rid, foreign_key):
            parent._read([foreign_key])
        raw = env.cache.get(parent._name, rid, foreign_key)
        domain = (("id", "=", int(raw)),) if raw is not None else _empty_domain()
        qb = QueryBuilder(model_cls=comodel_cls, env=env, _domain=domain)
        return cls(
            env=env,
            parent=parent,
            comodel_name=comodel_name,
            _qb=qb,
            foreign_key=foreign_key,
        )


@dataclass(frozen=True)
class HasMany(Relation):
    """One2many-style relation filtering comodel by inverse Many2one."""

    inverse_name: str

    @classmethod
    def for_parent(cls, parent, comodel_name: str, inverse_name: str) -> HasMany:
        env = parent.env
        comodel_cls = env.registry[comodel_name]
        inverse = comodel_cls._fields.get(inverse_name)
        if not isinstance(inverse, Many2one):
            raise ValueError(
                f"{comodel_name}.{inverse_name} must be a Many2one for has_many()"
            )
        if inverse.comodel_name != parent._name:
            raise ValueError(
                f"{comodel_name}.{inverse_name} must point at {parent._name!r}, "
                f"got {inverse.comodel_name!r}"
            )
        if not parent._ids:
            domain = _empty_domain()
        elif len(parent._ids) == 1:
            domain = ((inverse_name, "=", parent._ids[0]),)
        else:
            domain = ((inverse_name, "in", list(parent._ids)),)
        qb = QueryBuilder(model_cls=comodel_cls, env=env, _domain=domain)
        return cls(
            env=env,
            parent=parent,
            comodel_name=comodel_name,
            _qb=qb,
            inverse_name=inverse_name,
        )


class HasOne(HasMany):
    """HasMany constrained to at most one row (convenience)."""

    def first(self):
        return self._qb.limit(1).first()


@dataclass(frozen=True)
class BelongsToMany(Relation):
    """Many2many via an existing field on the parent model."""

    field_name: str

    @classmethod
    def for_parent(cls, parent, comodel_name: str, field_name: str) -> BelongsToMany:
        env = parent.env
        field = parent._fields.get(field_name)
        if not isinstance(field, Many2many):
            raise ValueError(
                f"{parent._name}.{field_name} must be a Many2many for "
                f"belongs_to_many()"
            )
        if field.comodel_name != comodel_name:
            raise ValueError(
                f"{parent._name}.{field_name} targets {field.comodel_name!r}, "
                f"not {comodel_name!r}"
            )
        parent.ensure_one()
        cached = parent[field_name]
        target_ids = cached._ids
        comodel_cls = env.registry[comodel_name]
        domain = (
            (("id", "in", list(target_ids)),) if target_ids else _empty_domain()
        )
        qb = QueryBuilder(model_cls=comodel_cls, env=env, _domain=domain)
        return cls(
            env=env,
            parent=parent,
            comodel_name=comodel_name,
            _qb=qb,
            field_name=field_name,
        )
