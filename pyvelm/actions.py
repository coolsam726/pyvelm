"""Backward-compatible re-export of ``ir.actions.server``."""
from __future__ import annotations

from pyvelm._bundled_path import ensure_builtin_modules_path

ensure_builtin_modules_path()
from base.models.ir_actions_server import ServerAction  # noqa: E402

__all__ = ["ServerAction"]
