"""Backward-compatible re-export of ``ir.cron``."""
from __future__ import annotations

from pyvelm._bundled_path import ensure_builtin_modules_path
from pyvelm.fields import Datetime as _DatetimeField  # noqa: F401

ensure_builtin_modules_path()
from base.models.ir_cron import (  # noqa: E402
    CronJob,
    _INTERVAL_DELTAS,
)

__all__ = ["CronJob", "_INTERVAL_DELTAS", "_DatetimeField"]
