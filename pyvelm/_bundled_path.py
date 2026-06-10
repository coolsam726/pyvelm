"""Ensure bundled addon roots are importable as top-level packages (``base``, …)."""
from __future__ import annotations

import sys
from pathlib import Path


def ensure_builtin_modules_path() -> None:
    """Insert ``pyvelm/modules`` on ``sys.path`` when not already present."""
    root = Path(__file__).resolve().parent / "modules"
    entry = str(root)
    if entry not in sys.path:
        sys.path.insert(0, entry)
