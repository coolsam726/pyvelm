"""Backward-compatible re-export of ``mail.compose.message``."""
from __future__ import annotations

from pyvelm._bundled_path import ensure_builtin_modules_path

ensure_builtin_modules_path()
from mail_compose.models.mail_compose_message import (  # noqa: E402
    MailCompose,
    _EMAIL_FIELD_NAMES,
    _EMAIL_M2O_PATHS,
    _resolve_default_to,
)

__all__ = [
    "MailCompose",
    "_EMAIL_FIELD_NAMES",
    "_EMAIL_M2O_PATHS",
    "_resolve_default_to",
]
