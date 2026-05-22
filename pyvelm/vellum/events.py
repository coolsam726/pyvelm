"""In-code model events (``@on("creating")``, …)."""
from __future__ import annotations

from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable)

PYVELM_EVENT = "__pyvelm_event__"

VALID_EVENTS = frozenset({
    "creating",
    "created",
    "updating",
    "updated",
    "saving",
    "saved",
    "deleting",
    "deleted",
})


def on(event: str) -> Callable[[F], F]:
    """Register a recordset method as a Vellum lifecycle listener."""
    if event not in VALID_EVENTS:
        raise ValueError(
            f"Unknown Vellum event {event!r}; expected one of {sorted(VALID_EVENTS)}"
        )

    def decorator(fn: F) -> F:
        setattr(fn, PYVELM_EVENT, event)
        return fn

    return decorator


def collect_events(namespace: dict) -> dict[str, list[str]]:
    """Map event name -> method names (class ``__dict__`` order)."""
    events: dict[str, list[str]] = {}
    for name, attr in namespace.items():
        event = getattr(attr, PYVELM_EVENT, None)
        if event:
            events.setdefault(event, []).append(name)
    return events


def merge_events(bases) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for base in bases:
        if base is object:
            continue
        for event, names in (getattr(base, "_vellum_events", None) or {}).items():
            merged.setdefault(event, []).extend(names)
    return merged


def fire(
    model_cls,
    event: str,
    records,
    *,
    vals: dict[str, Any] | None = None,
) -> None:
    """Invoke all handlers registered for *event* on *model_cls*."""
    handlers = (getattr(model_cls, "_vellum_events", None) or {}).get(event, [])
    for method_name in handlers:
        method = getattr(model_cls, method_name)
        if vals is not None:
            method(records, vals=vals)
        else:
            method(records)
