"""DSN normalisation and capability resolution."""
from __future__ import annotations

from urllib.parse import urlparse

from .capabilities import DialectCapabilities
from .dialects import dialect_capabilities, normalize_dsn_with_dialects


def normalize_dsn(dsn: str) -> str:
    """Normalise legacy DSNs to SQLAlchemy URL form."""
    dsn = (dsn or "").strip()
    if not dsn:
        raise ValueError("DSN is empty")
    return normalize_dsn_with_dialects(dsn)


def to_psycopg_dsn(dsn: str) -> str:
    """Return a libpq/psycopg connection string from a SQLAlchemy URL."""
    normalized = normalize_dsn(dsn)
    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "").split("+", 1)[0].lower()
    if scheme not in ("postgresql", "postgres"):
        raise ValueError(
            f"to_psycopg_dsn expects a PostgreSQL URL, got scheme {scheme!r}"
        )
    netloc = parsed.netloc
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"postgresql://{netloc}{path}{query}"


def capabilities_from_dsn(dsn: str) -> DialectCapabilities:
    parsed = urlparse(normalize_dsn(dsn))
    scheme = (parsed.scheme or "").split("+", 1)[0].lower()
    return dialect_capabilities(scheme)
