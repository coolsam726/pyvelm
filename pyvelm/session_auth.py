"""Session cookie helpers — DB-backed tokens vs signed stateless cookies.

On long-lived servers (Docker, gunicorn) sessions are random tokens stored on
``res.users.session_token`` and looked up per request.

On serverless hosts (Vercel, Lambda) each invocation may get its own ephemeral
SQLite copy under ``/tmp``, so a DB-stored token written at login is invisible
to the next request. There we mint an HMAC-signed cookie that carries ``uid``
and expiry instead — no shared writable store required.
"""
from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import os
import secrets
import time
from typing import TYPE_CHECKING

from pyvelm.database import is_serverless_runtime

if TYPE_CHECKING:
    from pyvelm.env import Environment

_SESSION_VERSION = "v1"
SESSION_COOKIE_MAX_AGE = 7 * 24 * 3600


@functools.lru_cache(maxsize=1)
def uses_stateless_sessions() -> bool:
    """True when session state must live in the cookie, not the database."""
    flag = os.environ.get("PYVELM_STATELESS_SESSIONS", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    if is_serverless_runtime():
        return True
    # Bundled SQLite copied to /tmp (Vercel demo) — DB tokens are not shared
    # across invocations even when VERCEL is unset in a custom host.
    try:
        from pyvelm.database import (
            capabilities_from_dsn,
            normalize_dsn,
            resolve_sqlite_dsn_for_runtime,
            sqlite_file_path,
        )

        raw = (os.environ.get("PYVELM_DSN") or "").strip()
        if raw:
            dsn = resolve_sqlite_dsn_for_runtime(normalize_dsn(raw))
            if capabilities_from_dsn(dsn).name == "sqlite":
                path = sqlite_file_path(dsn)
                if path and path.startswith("/tmp/"):
                    return True
    except Exception:
        pass
    return False


def session_signing_key() -> bytes:
    """Secret for HMAC session cookies."""
    raw = (os.environ.get("PYVELM_SECRET_KEY") or "").strip()
    if raw:
        return raw.encode("utf-8")
    seed = (
        os.environ.get("VERCEL_URL")
        or os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
        or "pyvelm-dev"
    )
    return hashlib.sha256(f"{seed}:pyvelm-session-v1".encode()).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def mint_session_cookie(uid: int, *, now: float | None = None) -> str:
    """Return a signed session cookie value for *uid*."""
    ts = int(now if now is not None else time.time())
    exp = ts + SESSION_COOKIE_MAX_AGE
    payload = f"{uid}:{exp}".encode()
    sig = hmac.new(session_signing_key(), payload, hashlib.sha256).digest()
    return f"{_SESSION_VERSION}.{_b64url_encode(payload)}.{_b64url_encode(sig)}"


def verify_session_cookie(token: str, *, now: float | None = None) -> int | None:
    """Verify a signed cookie and return ``uid``, or ``None``."""
    if not token or not uses_stateless_sessions():
        return None
    parts = token.split(".", 2)
    if len(parts) != 3 or parts[0] != _SESSION_VERSION:
        return None
    try:
        payload = _b64url_decode(parts[1])
        sig = _b64url_decode(parts[2])
    except (ValueError, binascii.Error):
        return None
    expected = hmac.new(session_signing_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        uid_s, exp_s = payload.decode("ascii").split(":", 1)
        uid = int(uid_s)
        exp = int(exp_s)
    except (ValueError, UnicodeDecodeError):
        return None
    if uid < 1:
        return None
    ts = int(now if now is not None else time.time())
    if exp < ts:
        return None
    return uid


def _verify_user_active(env: "Environment", uid: int) -> int | None:
    if "res.users" not in env.registry:
        return None
    users = env.sudo()["res.users"].search(
        [("id", "=", uid), ("active", "=", True)], limit=1
    )
    if not users:
        return None
    users.ensure_one()
    return users.id


def resolve_session_uid(env: "Environment", token: str | None) -> int | None:
    """Resolve a session cookie to ``uid`` (stateless or DB-backed)."""
    if not token:
        return None
    if uses_stateless_sessions():
        uid = verify_session_cookie(token)
        if uid is None:
            return None
        return _verify_user_active(env, uid)
    if "res.users" not in env.registry:
        return None
    users = env.sudo()["res.users"].search(
        [("session_token", "=", token), ("active", "=", True)], limit=1
    )
    if not users:
        return None
    users.ensure_one()
    return users.id


def establish_session(env: "Environment", uid: int) -> str:
    """Create a session for *uid* and return the cookie value."""
    if uses_stateless_sessions():
        return mint_session_cookie(uid)
    token = secrets.token_hex(32)
    with env.transaction():
        env.sudo()["res.users"].browse(uid).write({"session_token": token})
    return token


def revoke_session(env: "Environment", token: str | None) -> None:
    """Invalidate a DB-backed session; no-op for stateless cookies."""
    if not token or uses_stateless_sessions():
        return
    if "res.users" not in env.registry:
        return
    users = env.sudo()["res.users"].search([("session_token", "=", token)], limit=1)
    if users:
        with env.transaction():
            users.write({"session_token": None})
