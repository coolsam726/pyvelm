"""Immutable SQL query builder for Vellum-opted models."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Iterator

from pyvelm.env import Environment

from .soft_delete import soft_delete_domain_leaves


def _leaf(field: str, op: str, value: Any) -> tuple[str, str, Any]:
    return (field, op, value)


def _normalize_where(
    field: str, op: str | None = None, value: Any = None
) -> tuple[str, str, Any]:
    """``where("x", v)`` and ``where("x", ">", v)`` forms."""
    if op is None:
        return _leaf(field, "=", value)
    if value is None and op not in ("=", "!=", "<", "<=", ">", ">=", "in", "not in", "like", "ilike"):
        return _leaf(field, "=", op)
    return _leaf(field, op, value)


@dataclass(frozen=True)
class QueryBuilder:
    """Chainable, immutable builder compiling to ``BaseModel.search`` domains."""

    model_cls: type
    env: Environment
    _domain: tuple[tuple[str, str, Any], ...] = ()
    _order: str | None = None
    _limit: int | None = None
    _offset: int = 0
    _eager: tuple[str, ...] = ()
    _with_counts: tuple[str, ...] = ()
    _trashed_mode: str = "default"  # default | with | only

    def _replace(self, **kwargs) -> QueryBuilder:
        return replace(self, **kwargs)

    def _append_domain(self, *leaves: tuple[str, str, Any]) -> QueryBuilder:
        return self._replace(_domain=self._domain + leaves)

    def _call_scope(self, name: str, *args, **kwargs) -> QueryBuilder:
        scopes = getattr(self.model_cls, "_vellum_scopes", None) or {}
        if name not in scopes:
            raise AttributeError(
                f"scope {name!r} is not defined on {self.model_cls._name}"
            )
        return scopes[name](self, *args, **kwargs)

    def __getattr__(self, name: str):
        scopes = getattr(self.model_cls, "_vellum_scopes", None) or {}
        if name not in scopes:
            raise AttributeError(name)

        def scope_method(*args, **kwargs):
            return self._call_scope(name, *args, **kwargs)

        return scope_method

    # --- filters ---------------------------------------------------------

    def where(
        self, field: str, op: str | Any = None, value: Any = None
    ) -> QueryBuilder:
        return self._append_domain(_normalize_where(field, op, value))

    def where_in(self, field: str, values: Iterable[Any]) -> QueryBuilder:
        return self._append_domain(_leaf(field, "in", list(values)))

    def where_not_in(self, field: str, values: Iterable[Any]) -> QueryBuilder:
        return self._append_domain(_leaf(field, "not in", list(values)))

    def where_like(self, field: str, pattern: str) -> QueryBuilder:
        return self._append_domain(_leaf(field, "like", pattern))

    def where_ilike(self, field: str, pattern: str) -> QueryBuilder:
        return self._append_domain(_leaf(field, "ilike", pattern))

    def where_null(self, field: str) -> QueryBuilder:
        return self._append_domain(_leaf(field, "=", None))

    def where_not_null(self, field: str) -> QueryBuilder:
        return self._append_domain(_leaf(field, "!=", None))

    def where_between(
        self, field: str, low: Any, high: Any
    ) -> QueryBuilder:
        return self._append_domain(
            _leaf(field, ">=", low),
            _leaf(field, "<=", high),
        )

    def or_where(
        self, field: str, op: str | Any = None, value: Any = None
    ) -> QueryBuilder:
        """OR one condition; use ``where_any`` for multiple arms."""
        if op is None or (
            value is None
            and op not in ("=", "!=", "<", "<=", ">", ">=", "in", "not in", "like", "ilike")
        ):
            return self.where_any((field, op))
        return self.where_any((field, op, value))

    def where_any(self, *conditions: tuple) -> QueryBuilder:
        """OR together several conditions (maps to domain ``__or__``)."""
        leaves: list[tuple[str, str, Any]] = []
        for cond in conditions:
            if len(cond) == 2:
                leaves.append(_normalize_where(cond[0], None, cond[1]))
            elif len(cond) == 3:
                leaves.append(_normalize_where(cond[0], cond[1], cond[2]))
            else:
                raise ValueError(f"Invalid where_any condition: {cond!r}")
        return self._append_domain(("__or__", "=", leaves))

    def order_by(self, field: str, direction: str = "asc") -> QueryBuilder:
        col = self._column_ref(field)
        dir_sql = "DESC" if str(direction).lower() in ("desc", "descending") else "ASC"
        clause = f'{col} {dir_sql}'
        if self._order:
            clause = f"{self._order}, {clause}"
        return self._replace(_order=clause)

    def latest(self, field: str = "id") -> QueryBuilder:
        return self.order_by(field, "desc")

    def oldest(self, field: str = "id") -> QueryBuilder:
        return self.order_by(field, "asc")

    def limit(self, n: int) -> QueryBuilder:
        return self._replace(_limit=int(n))

    def offset(self, n: int) -> QueryBuilder:
        return self._replace(_offset=int(n))

    def with_(self, *paths: str) -> QueryBuilder:
        """Eager-load relational paths after the main query terminates."""
        merged = self._eager + paths
        return self._replace(_eager=merged)

    def with_count(self, *fields: str) -> QueryBuilder:
        """Attach relation counts via :meth:`Vellum.count_of` after ``get()``."""
        merged = self._with_counts + fields
        return self._replace(_with_counts=merged)

    def with_trashed(self) -> QueryBuilder:
        """Include soft-deleted rows (models using :class:`SoftDeletes`)."""
        return self._replace(_trashed_mode="with")

    def only_trashed(self) -> QueryBuilder:
        """Return only soft-deleted rows."""
        return self._replace(_trashed_mode="only")

    def _search_domain(self) -> list[tuple[str, str, Any]]:
        domain = list(self._domain)
        domain.extend(soft_delete_domain_leaves(self.model_cls, self._trashed_mode))
        return domain

    # --- terminators -----------------------------------------------------

    def _model(self):
        return self.model_cls(self.env, ())

    def _terminate(self, records):
        if self._eager:
            from .eager import eager_load

            eager_load(self.env, records, self._eager)
        if self._with_counts:
            from .counts import apply_with_counts

            apply_with_counts(self.env, records, self._with_counts)
        return records

    def get(self):
        records = self._model().search(
            self._search_domain(),
            limit=self._limit,
            offset=self._offset,
            order=self._order,
        )
        return self._terminate(records)

    def first(self):
        records = self._model().search(
            self._search_domain(),
            limit=1,
            offset=self._offset,
            order=self._order,
        )
        return self._terminate(records)

    def find(self, record_id: int):
        rec = self._model().browse(record_id)
        if not rec:
            return rec
        found = self._model().search(
            [("id", "=", record_id), *self._search_domain()],
            limit=1,
        )
        return found if found else self._model().browse(())

    def find_or_fail(self, record_id: int):
        rec = self.find(record_id)
        if not rec:
            raise ValueError(
                f"No {self.model_cls._name} record with id={record_id!r} "
                f"matching the current query."
            )
        return rec

    def pluck(self, field: str) -> list[Any]:
        return self.get().pluck(field)

    def count(self) -> int:
        return self._model().search_count(self._search_domain())

    def exists(self) -> bool:
        return bool(
            self._model().search(
                self._search_domain(),
                limit=1,
            )
        )

    def chunk(self, size: int) -> Iterator:
        if size < 1:
            raise ValueError("chunk size must be >= 1")
        offset = self._offset
        while True:
            page = self.offset(offset).limit(size).get()
            if not page:
                break
            yield page
            if len(page) < size:
                break
            offset += size

    def paginate(
        self, page: int = 1, per_page: int = 20
    ) -> dict[str, Any]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if per_page < 1:
            raise ValueError("per_page must be >= 1")
        total = self.count()
        offset = (page - 1) * per_page
        items = self.offset(offset).limit(per_page).get()
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    def _column_ref(self, field: str) -> str:
        if field == "id":
            return '"id"'
        if field not in self.model_cls._fields:
            raise ValueError(
                f"Unknown field {field!r} on {self.model_cls._name}"
            )
        col = self.model_cls._fields[field].column
        return f'"{col}"'
