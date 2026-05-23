"""Mass-assignment policy (``_fillable`` / ``_guarded``)."""
from __future__ import annotations

from typing import Any


def validate_mass_assignment_config(cls) -> None:
    fillable = getattr(cls, "_fillable", None)
    guarded = getattr(cls, "_guarded", None)
    if fillable is not None and guarded is not None:
        raise TypeError(
            f"{cls._name}: declare either _fillable or _guarded, not both."
        )


def apply_vellum_mass_assignment_defaults(cls) -> None:
    """Default Laravel-style policy on Vellum models: guard system columns."""
    if getattr(cls, "_fillable", None) is not None:
        return
    if getattr(cls, "_guarded", None) is not None:
        return
    from .timestamps import timestamp_columns

    guarded = ["id", *timestamp_columns(cls)]
    cls._guarded = guarded


def filter_mass_assignment(cls, vals: dict[str, Any]) -> dict[str, Any]:
    """Drop or reject keys per ``_fillable`` / ``_guarded`` on *cls*."""
    fillable = getattr(cls, "_fillable", None)
    guarded = getattr(cls, "_guarded", None)
    if fillable is None and guarded is None:
        return vals
    strict = bool(getattr(cls, "_strict_fillable", False))
    if fillable is not None:
        allowed = set(fillable)
        blocked = [k for k in vals if k not in allowed]
        filtered = {k: v for k, v in vals.items() if k in allowed}
    else:
        blocked_set = set(guarded)
        if "*" in blocked_set:
            blocked = list(vals.keys())
            filtered = {}
        else:
            blocked = [k for k in vals if k in blocked_set]
            filtered = {k: v for k, v in vals.items() if k not in blocked_set}
    if blocked and strict:
        raise ValueError(
            f"Mass assignment blocked for {cls._name}: {', '.join(sorted(blocked))}"
        )
    return filtered
