"""Human-readable file size formatting.

Top-level so unit tests can ``from pyvelm.file_size import human_size``
without going through the poisoned ``pyvelm.modules`` namespace, and so
the Jinja template environment can register it as a filter once.
"""

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def human_size(num_bytes: int | None) -> str:
    """Return a compact human-readable size string.

    ``None`` / ``0`` / negative / non-numeric values render as ``"—"``
    so templates can write ``{{ row.file_size | human_size }}`` without
    extra guard clauses.
    """
    if num_bytes is None:
        return "—"
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "—"
    if n <= 0:
        return "—"
    idx = 0
    while n >= 1024 and idx < len(_UNITS) - 1:
        n /= 1024
        idx += 1
    if idx == 0:
        return f"{int(n)} {_UNITS[idx]}"
    return f"{n:.1f} {_UNITS[idx]}"
