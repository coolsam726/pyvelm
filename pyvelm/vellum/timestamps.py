"""Automatic ``created_at`` / ``updated_at`` for Vellum models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pyvelm import Datetime


def uses_timestamps(model_cls) -> bool:
    """True when automatic timestamps are enabled (Laravel default: on)."""
    return bool(getattr(model_cls, "_timestamps", True))


def created_at_column(model_cls) -> str | None:
    col = getattr(model_cls, "_CREATED_AT", "created_at")
    return col if col else None


def updated_at_column(model_cls) -> str | None:
    col = getattr(model_cls, "_UPDATED_AT", "updated_at")
    return col if col else None


def timestamp_columns(model_cls) -> tuple[str, ...]:
    """Stored timestamp column names configured on *model_cls*."""
    if not uses_timestamps(model_cls):
        return ()
    cols: list[str] = []
    for name in (created_at_column(model_cls), updated_at_column(model_cls)):
        if name and name in model_cls._fields:
            cols.append(name)
    return tuple(cols)


def is_vellum_timestamp_field(model_cls, fname: str) -> bool:
    """True when *fname* is a system-managed Vellum timestamp column."""
    return fname in timestamp_columns(model_cls)


def utc_now() -> datetime:
    """Naive UTC ``datetime`` for ``timestamp`` columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _inject_timestamp_field(cls, name: str, label: str) -> None:
    if name in cls._fields:
        return
    field = Datetime(string=label, readonly=True)
    field.bind(cls._name, name)
    merged = dict(cls._fields)
    merged[name] = field
    cls._fields = merged
    if name not in cls.__dict__:
        setattr(cls, name, field)


def install_vellum_timestamps(cls) -> None:
    """Add ``created_at`` / ``updated_at`` fields when timestamps are enabled."""
    if not getattr(cls, "_name", None) or not uses_timestamps(cls):
        return
    created = created_at_column(cls)
    updated = updated_at_column(cls)
    if created:
        _inject_timestamp_field(cls, created, "Created At")
    if updated:
        _inject_timestamp_field(cls, updated, "Updated At")


def apply_timestamp_vals(
    cls, vals: dict[str, Any], *, updating: bool
) -> dict[str, Any]:
    """Merge automatic timestamps into *vals* (after mass-assignment filtering)."""
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
