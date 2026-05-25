"""Vellum re-exports framework timestamps (backward compatible)."""
from __future__ import annotations

from pyvelm.timestamps import (
    apply_timestamp_vals,
    created_at_column,
    inject_timestamp_fields,
    install_timestamps,
    is_system_timestamp_field,
    is_vellum_timestamp_field,
    timestamp_columns,
    updated_at_column,
    uses_timestamps,
    utc_now,
)

install_vellum_timestamps = install_timestamps

__all__ = [
    "apply_timestamp_vals",
    "created_at_column",
    "inject_timestamp_fields",
    "install_timestamps",
    "install_vellum_timestamps",
    "is_system_timestamp_field",
    "is_vellum_timestamp_field",
    "timestamp_columns",
    "updated_at_column",
    "uses_timestamps",
    "utc_now",
]
