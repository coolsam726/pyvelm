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
        blocked = [k for k in vals if k in blocked_set]
        filtered = {k: v for k, v in vals.items() if k not in blocked_set}
    if blocked and strict:
        raise ValueError(
            f"Mass assignment blocked for {cls._name}: {', '.join(sorted(blocked))}"
        )
    return filtered
