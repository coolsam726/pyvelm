"""Purge audit tables older than ``PYVELM_AUDIT_RETENTION_DAYS``."""
from __future__ import annotations

import os
from datetime import timedelta

from pyvelm.timestamps import utc_now

_AUDIT_MODELS = (
    "ir.audit.log",
    "ir.login.log",
    "ir.user.lifecycle",
)


def retention_days() -> int:
    raw = (os.environ.get("PYVELM_AUDIT_RETENTION_DAYS") or "90").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 90


def purge_audit_logs(env) -> int:
    """Delete rows older than the retention window. Returns total purged."""
    days = retention_days()
    cutoff = utc_now() - timedelta(days=days)
    total = 0
    sudo = env.sudo()
    for model_name in _AUDIT_MODELS:
        if model_name not in env.registry:
            continue
        Model = sudo[model_name]
        stale = Model.search([("created_at", "<", cutoff)])
        if stale:
            count = len(stale._ids)
            stale.unlink()
            total += count
    return total
