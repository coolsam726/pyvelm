"""Backward-compatible re-export of ``mail.template``."""
from __future__ import annotations

from pyvelm._bundled_path import ensure_builtin_modules_path
from pyvelm.mail_template_render import (  # noqa: F401
    build_mail_template_context,
    render_mail_template_string,
)

ensure_builtin_modules_path()
from base.models.mail_template import MailTemplate  # noqa: E402

__all__ = [
    "MailTemplate",
    "build_mail_template_context",
    "render_mail_template_string",
]
