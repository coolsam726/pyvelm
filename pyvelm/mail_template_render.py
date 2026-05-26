"""Jinja2 rendering helpers for ``mail.template`` (no ORM models)."""

from __future__ import annotations

import re
from typing import Any

import jinja2
from jinja2.sandbox import SandboxedEnvironment

_LEGACY_EXPR = re.compile(r"\$\{([^}]+)\}")

_jinja_env = SandboxedEnvironment(
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _normalize_template_source(source: str) -> str:
    if not source:
        return ""
    return _LEGACY_EXPR.sub(r"{{ \1 }}", source)


def build_mail_template_context(
    env,
    *,
    model: str,
    record=None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the dict passed to Jinja when rendering a template."""
    ctx: dict[str, Any] = {"ctx": dict(extra or {})}

    if record is not None and hasattr(record, "_ids") and record._ids:
        ctx["object"] = record
    elif model and model in env.registry:
        ctx["object"] = env[model]
    else:
        ctx["object"] = None

    if env.uid is not None and "res.users" in env.registry:
        ctx["user"] = env["res.users"].browse(env.uid)
    else:
        ctx["user"] = env["res.users"](env, ()) if "res.users" in env.registry else None

    company = None
    if "res.company" in env.registry:
        cid = env.company_id
        if cid is not None:
            company = env["res.company"].browse(cid)
        elif ctx.get("user") is not None and getattr(ctx["user"], "_ids", None):
            u = ctx["user"]
            if u._ids and getattr(u, "company_id", None):
                company = env["res.company"].browse(u.company_id.id)
        if company is None or not company._ids:
            rows = env["res.company"].search([], limit=1)
            company = rows if rows._ids else env["res.company"](env, ())
    ctx["company"] = company
    return ctx


def render_mail_template_string(source: str, context: dict[str, Any]) -> str:
    """Render *source* with Jinja2 (sandboxed, auto-escaped)."""
    normalized = _normalize_template_source(source or "")
    if not normalized.strip():
        return ""
    try:
        return _jinja_env.from_string(normalized).render(**context)
    except jinja2.TemplateError as exc:
        raise ValueError(f"Email template syntax error: {exc}") from exc
