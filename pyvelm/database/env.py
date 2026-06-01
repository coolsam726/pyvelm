"""Environment variable helpers for application and test DSNs."""
from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

from .dsn import normalize_dsn

TEST_DSN_ENV = "PYVELM_DSN_TEST"


def load_testing_env() -> bool:
    """Load ``.env.testing`` when present (Laravel-style test overrides)."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return False
    path = find_dotenv(".env.testing", usecwd=True)
    if not path:
        return False
    load_dotenv(path, override=True)
    return True


def test_dsn_from_env() -> str | None:
    raw = os.environ.get(TEST_DSN_ENV)
    if not raw:
        return None
    return normalize_dsn(raw)


def require_test_dsn_from_env() -> str:
    dsn = test_dsn_from_env()
    if not dsn:
        raise SystemExit(
            f"{TEST_DSN_ENV} not set — configure a throwaway database for tests "
            "(copy .env.testing.example to .env.testing)."
        )
    return dsn


def app_dsn_from_env() -> str | None:
    raw = os.environ.get("PYVELM_DSN")
    if not raw:
        return None
    return normalize_dsn(raw)


def require_dsn_from_env() -> str:
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        raise SystemExit("PYVELM_DSN not set")
    return dsn


def dsn_display(dsn: str) -> str:
    """Return a DSN safe to print (password redacted)."""
    try:
        parsed = urlparse(normalize_dsn(dsn))
        scheme = (parsed.scheme or "").split("+", 1)[0].lower()
        if scheme == "sqlite":
            path = parsed.path or ""
            if parsed.netloc:
                path = f"/{parsed.netloc}{path}"
            return f"sqlite://{path or ':memory:'}"
        if parsed.scheme and parsed.hostname:
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:***@{netloc}"
            path = parsed.path or ""
            return urlunparse((parsed.scheme, netloc, path, parsed.params, "", ""))
    except Exception:
        pass
    return "<dsn>"


def is_serverless_runtime() -> bool:
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )


def uses_serverless_schema_wipe() -> bool:
    if is_serverless_runtime():
        return True
    flag = (os.environ.get("PYVELM_NUKE_SERVERLESS") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def nuke_dsn_from_env() -> str:
    raw = (os.environ.get("PYVELM_NUKE_DSN") or os.environ.get("PYVELM_DSN") or "").strip()
    if not raw:
        raise SystemExit("PYVELM_DSN not set")
    return normalize_dsn(raw)


def is_transaction_pooler_dsn(dsn: str) -> bool:
    try:
        parsed = urlparse(normalize_dsn(dsn))
        if parsed.port == 6543:
            return True
    except Exception:
        pass
    return ":6543" in (dsn or "")


def is_supabase_direct_host(dsn: str) -> bool:
    try:
        parsed = urlparse(normalize_dsn(dsn))
        host = (parsed.hostname or "").lower()
        return host.startswith("db.") and host.endswith(".supabase.co")
    except Exception:
        return False


def warn_if_poor_nuke_dsn(dsn: str) -> None:
    if not uses_serverless_schema_wipe():
        return
    import sys

    if is_transaction_pooler_dsn(dsn):
        print(
            "WARNING: Schema wipe through a transaction pooler (port 6543) can "
            "deadlock. Use a session pooler URL (port 5432) for PYVELM_NUKE_DSN.",
            file=sys.stderr,
        )
        return
    if is_supabase_direct_host(dsn):
        print(
            "WARNING: Supabase direct host db.*.supabase.co is often IPv6-only "
            "from serverless builders. Use *.pooler.supabase.com:5432 instead.",
            file=sys.stderr,
        )
