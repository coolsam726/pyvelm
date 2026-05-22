"""``@scope`` — chainable query modifiers on :class:`QueryBuilder`."""
from __future__ import annotations

from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

PYVELM_SCOPE = "__pyvelm_scope__"


def scope(fn: F) -> F:
    """Mark *fn* as a Vellum scope (first arg is the :class:`QueryBuilder`)."""
    setattr(fn, PYVELM_SCOPE, True)
    return fn
