"""Eloquent-style query builder on the registry's effective model class.

Always start from ``env["model.name"]`` or ``env.query("model.name")`` so
``_inherit`` merges are respected — not a stale import from a single module.

Example::

    posts = (
        env["blog.post"]
        .query()
        .where("active", "=", True)
        .where("views", ">", 100)
        .order_by("published_at", "desc")
        .limit(20)
        .get()
    )
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator, TYPE_CHECKING

from .domain import expand_or_groups, is_domain_leaf

if TYPE_CHECKING:
    from .env import Environment
    from .model import BaseModel

_MISSING = object()
_FIELD_RE = re.compile(r"^[\w.]+$")


@dataclass(frozen=True)
class Page:
    """Paginator result from :meth:`Query.paginate`."""

    items: "BaseModel"
    total: int
    page: int
    per_page: int

    @property
    def last_page(self) -> int:
        if self.per_page <= 0:
            return 1
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_more(self) -> bool:
        return self.page < self.last_page


class RecordNotFound(LookupError):
    """Raised by :meth:`Query.find_or_fail` when no row matches."""


class Query:
    """Fluent SQL search builder delegating to :meth:`BaseModel.search`."""

    __slots__ = ("_model_cls", "_env", "_domain", "_order", "_limit", "_offset")

    def __init__(self, model_cls: type, env: "Environment") -> None:
        self._model_cls = model_cls
        self._env = env
        self._domain: list = []
        self._order: str | None = None
        self._limit: int | None = None
        self._offset: int = 0

    @classmethod
    def for_model(cls, model_cls: type, env: "Environment") -> "Query":
        return cls(model_cls, env)

    # ---- constraints ------------------------------------------------

    def where(
        self,
        field: str,
        op: str | Any = _MISSING,
        value: Any = _MISSING,
        *,
        all: bool = False,
    ) -> "Query":
        """Add a domain leaf (implicit AND with prior constraints)."""
        field, op, value = self._parse_predicate(field, op, value)
        self._validate_field(field)
        leaf: tuple = (field, op, value)
        if all:
            leaf = (field, op, value, {"all": True})
        self._domain.append(leaf)
        return self

    def or_where(
        self,
        field: str,
        op: str | Any = _MISSING,
        value: Any = _MISSING,
        *,
        all: bool = False,
    ) -> "Query":
        """Add a leaf OR-ed with the current AND-group."""
        field, op, value = self._parse_predicate(field, op, value)
        self._validate_field(field)
        leaf: tuple = (field, op, value)
        if all:
            leaf = (field, op, value, {"all": True})
        if not self._domain:
            self._domain.append(leaf)
            return self
        if len(self._domain) == 1 and is_domain_leaf(self._domain[0]):
            self._domain = ["|", self._domain[0], leaf]
            return self
        n = len(self._domain)
        self._domain = ["|"] + ["&"] * (n - 1) + list(self._domain) + [leaf]
        return self

    def where_in(self, field: str, values: list | tuple) -> "Query":
        return self.where(field, "in", list(values))

    def where_not_in(self, field: str, values: list | tuple) -> "Query":
        return self.where(field, "not in", list(values))

    def where_null(self, field: str) -> "Query":
        return self.where(field, "=", None)

    def where_not_null(self, field: str) -> "Query":
        return self.where(field, "!=", None)

    def where_any(self, leaves: list[tuple]) -> "Query":
        """OR group of leaves — same as legacy ``("__or__", "=", [...])``."""
        if not leaves:
            return self
        or_part = expand_or_groups([("__or__", "=", list(leaves))])
        if self._domain:
            self._domain = list(self._domain) + list(or_part)
        else:
            self._domain = list(or_part)
        return self

    def order_by(self, field: str, direction: str = "asc") -> "Query":
        direction = direction.strip().upper()
        if direction not in ("ASC", "DESC"):
            raise ValueError("direction must be 'asc' or 'desc'")
        self._validate_field(field, allow_id=True)
        self._order = f'"{field}" {direction}'
        return self

    def limit(self, n: int) -> "Query":
        if n < 0:
            raise ValueError("limit must be >= 0")
        self._limit = int(n)
        return self

    def offset(self, n: int) -> "Query":
        if n < 0:
            raise ValueError("offset must be >= 0")
        self._offset = int(n)
        return self

    # ---- execution --------------------------------------------------

    def get(self) -> "BaseModel":
        """Run the query and return a recordset."""
        return self._recordset().search(
            self._domain or None,
            limit=self._limit,
            offset=self._offset,
            order=self._order,
        )

    def first(self) -> "BaseModel":
        """First matching row, or an empty recordset."""
        return self._clone().limit(1).get()

    def find(self, record_id: int) -> "BaseModel":
        return self._clone().where("id", "=", int(record_id)).limit(1).get()

    def find_or_fail(self, record_id: int) -> "BaseModel":
        rec = self.find(record_id)
        if not rec:
            raise RecordNotFound(
                f"{self._model_cls._name} #{record_id} not found"
            )
        return rec

    def count(self) -> int:
        return self._recordset().search_count(self._domain or None)

    def exists(self) -> bool:
        return self.count() > 0

    def pluck(self, field: str) -> list[Any]:
        rows = self.get().read([field])
        return [row[field] for row in rows]

    def value(self, field: str) -> Any:
        rows = self.pluck(field)
        return rows[0] if rows else None

    def paginate(self, page: int = 1, per_page: int = 15) -> Page:
        page = max(1, int(page))
        per_page = max(1, int(per_page))
        total = self.count()
        items = (
            self._clone()
            .offset((page - 1) * per_page)
            .limit(per_page)
            .get()
        )
        return Page(items=items, total=total, page=page, per_page=per_page)

    def chunk(self, size: int) -> Iterator["BaseModel"]:
        size = max(1, int(size))
        offset = 0
        while True:
            batch = Query.for_model(self._model_cls, self._env)
            batch._domain = list(self._domain)
            batch._order = self._order
            batch._limit = size
            batch._offset = offset
            rows = batch.get()
            if not rows:
                break
            yield rows
            if len(rows._ids) < size:
                break
            offset += size

    @property
    def domain(self) -> list:
        """Compiled domain list (read-only copy)."""
        return list(self._domain)

    # ---- internals --------------------------------------------------

    def _recordset(self) -> "BaseModel":
        return self._model_cls(self._env, ())

    def _clone(self) -> "Query":
        q = Query.for_model(self._model_cls, self._env)
        q._domain = list(self._domain)
        q._order = self._order
        q._limit = self._limit
        q._offset = self._offset
        return q

    @staticmethod
    def _parse_predicate(
        field: str, op: str | Any, value: Any
    ) -> tuple[str, str, Any]:
        if value is _MISSING:
            if op is _MISSING:
                raise TypeError("where() missing comparison value")
            if isinstance(op, str) and op in {
                "=",
                "!=",
                "<",
                "<=",
                ">",
                ">=",
                "in",
                "not in",
                "like",
                "ilike",
            }:
                raise TypeError("where() missing value")
            value = op
            op = "="
        elif op is _MISSING:
            op = "="
        return field, op, value

    @staticmethod
    def _validate_field(field: str, *, allow_id: bool = False) -> None:
        if allow_id and field == "id":
            return
        if not _FIELD_RE.fullmatch(field):
            raise ValueError(f"Invalid field name {field!r}")
