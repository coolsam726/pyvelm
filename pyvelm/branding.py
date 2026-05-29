"""White-label branding — per-company UI identity with env fallbacks.

Configure on **Settings → Companies** (``res.company``) or via environment:

- ``PYVELM_APP_NAME`` — replaces "pyvelm" in chrome and titles
- ``PYVELM_APP_TAGLINE`` — login subtitle
- ``PYVELM_LOGO_URL`` / ``PYVELM_LOGO_URL_DARK`` — logo for light / dark UI (dark falls back to light)
- ``PYVELM_FAVICON_URL`` — favicon URL (e.g. attachment download paths)
- ``PYVELM_COPYRIGHT`` — footer legal line
- ``PYVELM_SUPPORT_EMAIL`` / ``PYVELM_SUPPORT_URL`` — footer support links
- ``PYVELM_SHOW_POWERED_BY`` — ``0`` / ``false`` hides the powered-by line

Theme accent still comes from ``res.company.primary_color`` (see ``pyvelm.theme``).

Site entry (see ``pyvelm.home``):

- ``PYVELM_HOME_URL`` — post-login home (default ``/web/admin``; use ``/`` or a
  ``/web/views/…`` dashboard to mount the app home at the site root).
- ``PYVELM_LANDING`` — show a public landing page at ``/`` for anonymous visitors
  (default on; set ``0`` to send them straight to login).
"""
from __future__ import annotations

import os
from typing import Any

from .theme import company_theme_context

DEFAULT_APP_NAME = "pyvelm"
DEFAULT_TAGLINE = "Welcome back."


def _env_str(key: str) -> str:
    return (os.environ.get(key) or "").strip()


def _env_bool(key: str, default: bool = True) -> bool:
    raw = _env_str(key).lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _pick_str(company_val: str | None, env_key: str, default: str = "") -> str:
    from_co = (company_val or "").strip()
    if from_co:
        return from_co
    from_env = _env_str(env_key)
    if from_env:
        return from_env
    return default


def _load_company_branding(env, company_id: int | None) -> dict[str, Any] | None:
    if env is None or company_id is None or "res.company" not in env.registry:
        return None
    Company = env.with_company(None).sudo()["res.company"]
    if not Company.search([("id", "=", company_id)]):
        return None
    co = Company.browse(company_id)
    co.ensure_one()
    return {
        "app_name": co.app_name,
        "app_tagline": co.app_tagline,
        "logo_url": co.logo_url,
        "logo_url_dark": co.logo_url_dark,
        "favicon_url": co.favicon_url,
        "copyright_text": co.copyright_text,
        "support_email": co.support_email,
        "support_url": co.support_url,
        "show_powered_by": co.show_powered_by,
    }


def brand_dict(
    env=None,
    *,
    company_id: int | None = None,
) -> dict[str, Any]:
    """Resolved branding for templates (``brand`` context key)."""
    cid = env.company_id if (env is not None and company_id is None) else company_id
    co = _load_company_branding(env, cid) if env is not None else None

    app_name = _pick_str(
        co.get("app_name") if co else None,
        "PYVELM_APP_NAME",
        DEFAULT_APP_NAME,
    )
    tagline = _pick_str(
        co.get("app_tagline") if co else None,
        "PYVELM_APP_TAGLINE",
        DEFAULT_TAGLINE,
    )
    logo_url_light = _pick_str(co.get("logo_url") if co else None, "PYVELM_LOGO_URL")
    logo_url_dark = _pick_str(
        co.get("logo_url_dark") if co else None, "PYVELM_LOGO_URL_DARK"
    )
    if not logo_url_dark:
        logo_url_dark = logo_url_light
    favicon_url = _pick_str(co.get("favicon_url") if co else None, "PYVELM_FAVICON_URL")
    copyright_text = _pick_str(
        co.get("copyright_text") if co else None, "PYVELM_COPYRIGHT"
    )
    support_email = _pick_str(
        co.get("support_email") if co else None, "PYVELM_SUPPORT_EMAIL"
    )
    support_url = _pick_str(co.get("support_url") if co else None, "PYVELM_SUPPORT_URL")
    if co is not None:
        show_powered_by = bool(co.get("show_powered_by"))
    else:
        show_powered_by = _env_bool("PYVELM_SHOW_POWERED_BY", default=True)

    return {
        "app_name": app_name,
        "tagline": tagline,
        "logo_url": logo_url_light,
        "logo_url_light": logo_url_light,
        "logo_url_dark": logo_url_dark,
        "favicon_url": favicon_url,
        "copyright": copyright_text,
        "support_email": support_email,
        "support_url": support_url,
        "show_powered_by": show_powered_by,
        "has_logo": bool(logo_url_light),
        "has_favicon": bool(favicon_url),
    }


def branding_context(
    env=None,
    *,
    company_id: int | None = None,
) -> dict[str, Any]:
    """Theme CSS + ``brand`` dict for Jinja layouts."""
    ctx = company_theme_context(env, company_id=company_id)
    ctx["brand"] = brand_dict(env, company_id=company_id)
    return ctx


def default_brand_globals() -> dict[str, Any]:
    """Jinja globals when no ``Environment`` is available."""
    brand = brand_dict(None)
    return {
        "brand": brand,
        "company_primary_color": "",
        "company_theme_style": "",
    }
