"""Automatic ``created_at`` / ``updated_at`` for :class:`~pyvelm.model.BaseModel`.

Enabled by default (``_timestamps = True``). Set ``_timestamps = False`` on a
model to opt out. Customize column names with ``_CREATED_AT`` / ``_UPDATED_AT``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .fields import Datetime, Field


def resolve_timestamps_enabled(namespace: dict, bases: tuple) -> bool:
    """Whether automatic timestamps apply (class body wins, then bases)."""
    if "_timestamps" in namespace:
        return bool(namespace["_timestamps"])
    for base in bases:
        if "_timestamps" in getattr(base, "__dict__", {}):
            return bool(base._timestamps)
    return True


def uses_timestamps(model_cls) -> bool:
    """True when automatic timestamps are enabled."""
    return bool(getattr(model_cls, "_timestamps", True))


def created_at_column(model_cls) -> str | None:
    col = getattr(model_cls, "_CREATED_AT", "created_at")
    return col if col else None


def updated_at_column(model_cls) -> str | None:
    col = getattr(model_cls, "_UPDATED_AT", "updated_at")
    return col if col else None


def timestamp_columns(model_cls) -> tuple[str, ...]:
    """Stored timestamp field names configured on *model_cls*."""
    if not uses_timestamps(model_cls):
        return ()
    cols: list[str] = []
    for name in (created_at_column(model_cls), updated_at_column(model_cls)):
        if name and name in model_cls._fields:
            cols.append(name)
    return tuple(cols)


def is_system_timestamp_field(model_cls, fname: str) -> bool:
    """True when *fname* is a framework-managed timestamp column."""
    return fname in timestamp_columns(model_cls)


# Backward-compatible alias (Vellum-era name).
is_vellum_timestamp_field = is_system_timestamp_field


def utc_now() -> datetime:
    """Naive UTC ``datetime`` for ``timestamp`` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def inject_timestamp_fields(
    model_name: str,
    fields: dict[str, Field],
    *,
    created_at: str = "created_at",
    updated_at: str = "updated_at",
) -> None:
    """Add readonly Datetime fields when not already declared."""
    if created_at and created_at not in fields:
        f = Datetime(string="Created At", readonly=True)
        f.bind(model_name, created_at)
        fields[created_at] = f
    if updated_at and updated_at not in fields:
        f = Datetime(string="Updated At", readonly=True)
        f.bind(model_name, updated_at)
        fields[updated_at] = f


def install_timestamps(cls) -> None:
    """Ensure timestamp fields exist on a registered model class."""
    if not getattr(cls, "_name", None) or not uses_timestamps(cls):
        return
    merged = dict(cls._fields)
    inject_timestamp_fields(
        cls._name,
        merged,
        created_at=created_at_column(cls) or "created_at",
        updated_at=updated_at_column(cls) or "updated_at",
    )
    cls._fields = merged
    for name in timestamp_columns(cls):
        if name not in cls.__dict__:
            setattr(cls, name, cls._fields[name])


def apply_timestamp_vals(
    cls, vals: dict[str, Any], *, updating: bool
) -> dict[str, Any]:
    """Merge automatic timestamps into *vals* before persistence."""
    if not uses_timestamps(cls):
        return vals
    out = dict(vals)
    now = utc_now()
    if not updating:
        created = created_at_column(cls)
        if created and created in cls._fields and created not in out:
            out[created] = now
    updated = updated_at_column(cls)
    if updated and updated in cls._fields and updated not in out:
        out[updated] = now
    return out
