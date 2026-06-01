"""SQLite file path helpers and serverless runtime copy."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from .dsn import capabilities_from_dsn, normalize_dsn


def sqlite_file_path(dsn: str) -> str | None:
    parsed = urlparse(normalize_dsn(dsn))
    if parsed.scheme.split("+", 1)[0].lower() != "sqlite":
        return None
    raw = parsed.path or ""
    if raw.startswith("//"):
        return raw[1:]
    path = raw.lstrip("/")
    if parsed.netloc:
        path = f"/{parsed.netloc}/{path}" if path else f"/{parsed.netloc}"
    elif path and not path.startswith("/"):
        path = str(Path(path).resolve())
    return path or None


def _sqlite_url_for_path(path: str) -> str:
    return f"sqlite:///{Path(path).resolve()}"


def resolve_sqlite_dsn_for_runtime(dsn: str) -> str:
    from .env import is_serverless_runtime

    normalized = normalize_dsn(dsn)
    if capabilities_from_dsn(normalized).name != "sqlite":
        return normalized
    if not is_serverless_runtime():
        return normalized

    override = (os.environ.get("PYVELM_SQLITE_PATH") or "").strip()
    if override:
        return _sqlite_url_for_path(override)

    source = sqlite_file_path(normalized)
    if source:
        src = Path(source)
        if (
            str(src.resolve()).startswith("/tmp/")
            and src.is_file()
            and os.access(source, os.W_OK)
        ):
            return normalized

    stem = hashlib.sha256((source or normalized).encode()).hexdigest()[:12]
    dest = Path("/tmp") / f"pyvelm-{stem}.db"

    if dest.is_file():
        return _sqlite_url_for_path(str(dest))

    if source and Path(source).is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return _sqlite_url_for_path(str(dest))

    return _sqlite_url_for_path(str(dest))


def delete_sqlite_file(dsn: str) -> None:
    path = sqlite_file_path(dsn)
    if path:
        p = Path(path)
        if p.is_file():
            os.remove(p)
