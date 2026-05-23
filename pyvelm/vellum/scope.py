"""``@scope`` — chainable query modifiers on :class:`QueryBuilder`."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol, cast

if TYPE_CHECKING:
    from .query import QueryBuilder

PYVELM_SCOPE = "__pyvelm_scope__"


class ScopeFunction(Protocol):
    """First argument is the :class:`QueryBuilder`, not ``self``."""

    def __call__(
        self, qb: QueryBuilder, /, *args: Any, **kwargs: Any
    ) -> QueryBuilder: ...


def unwrap_scope_callable(attr: object) -> Callable | None:
    """Return the raw scope function from a class attribute (or ``None``)."""
    if isinstance(attr, staticmethod):
        return attr.__func__  # type: ignore[return-value]
    if callable(attr):
        return attr
    return None


def scope(fn: ScopeFunction) -> staticmethod:
    """Mark *fn* as a Vellum scope; registers as a static method on the model."""
    setattr(fn, PYVELM_SCOPE, True)
    return cast(staticmethod, staticmethod(fn))
