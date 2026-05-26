"""Site entry URL configuration (landing page + post-login home).

Environment:

- ``PYVELM_HOME_URL`` — where signed-in users land (default ``/web/admin``).
  Set to ``/`` to serve the configured home dashboard at the site root, or
  to any ``/web/views/<module>/<name>`` dashboard/list URL.
- ``PYVELM_LANDING`` — when truthy (default), anonymous ``/`` shows the public
  landing page; when ``0`` / ``false``, ``/`` redirects to login.
"""
from __future__ import annotations

import os
from urllib.parse import quote

from .branding import _env_bool

DEFAULT_HOME_URL = "/web/admin"


def home_url() -> str:
    """Normalized post-login home path (no query string)."""
    raw = (os.environ.get("PYVELM_HOME_URL") or DEFAULT_HOME_URL).strip()
    if not raw:
        return DEFAULT_HOME_URL
    if not raw.startswith("/"):
        raw = "/" + raw
    path = raw.split("?", 1)[0].rstrip("/")
    return path or "/"


def landing_enabled() -> bool:
    return _env_bool("PYVELM_LANDING", default=True)


def login_destination(next_param: str | None = None) -> str:
    """Resolve the post-login redirect target."""
    n = (next_param or "").strip()
    if n.startswith("/"):
        return n.split("?", 1)[0] or home_url()
    return home_url()


def login_url(*, next_path: str | None = None) -> str:
    """Build ``/login`` with an optional ``next`` query."""
    dest = login_destination(next_path)
    if dest in ("/login", "/login/"):
        return "/login"
    return f"/login?next={quote(dest, safe='')}"
