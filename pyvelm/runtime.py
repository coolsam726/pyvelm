"""Runtime environment (development vs production).

Set ``PYVELM_ENV`` to ``development`` or ``production`` (aliases:
``dev``, ``local``, ``prod``). Controls API docs exposure, cookie
``Secure`` flags, default log level, and dev-server reload behaviour.

Typical values:

- Local ``python -m app.serve`` → ``development`` (default for the dev
  server entrypoint).
- Docker / gunicorn → ``production`` (set in compose / `.env`).
"""
from __future__ import annotations

import os

DEVELOPMENT = "development"
PRODUCTION = "production"

_ALIASES = {
    "dev": DEVELOPMENT,
    "local": DEVELOPMENT,
    "development": DEVELOPMENT,
    "prod": PRODUCTION,
    "production": PRODUCTION,
}


def normalize_env(value: str) -> str:
    """Map env string to ``development`` or ``production``."""
    key = (value or "").strip().lower()
    if key not in _ALIASES:
        raise ValueError(
            f"Invalid PYVELM_ENV {value!r}. "
            f"Use development or production."
        )
    return _ALIASES[key]


def get_runtime_env(explicit: str | None = None) -> str:
    """Resolved runtime mode from explicit arg or ``PYVELM_ENV``."""
    if explicit is not None:
        return normalize_env(explicit)
    return normalize_env(os.environ.get("PYVELM_ENV", DEVELOPMENT))


def is_development(env: str | None = None) -> bool:
    return get_runtime_env(env) == DEVELOPMENT


def is_production(env: str | None = None) -> bool:
    return get_runtime_env(env) == PRODUCTION


def cookie_options(*, httponly: bool = True, env: str | None = None) -> dict:
    """Default keyword args for ``Response.set_cookie`` on auth cookies."""
    opts: dict = {
        "httponly": httponly,
        "samesite": "lax",
        "path": "/",
    }
    if is_production(env):
        opts["secure"] = True
    return opts
