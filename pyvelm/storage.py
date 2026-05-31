"""Pluggable blob storage for ``ir.attachment``.

The model row owns the metadata (name, mimetype, owning record); the
bytes live in a backend selected by ``PYVELM_ATTACHMENT_BACKEND``:

    local   (default)   On-disk under ``PYVELM_ATTACHMENT_DIR``
                        (defaults to ``./data/attachments``).
    db                  Bytes go in the row's own ``datas`` column —
                        no filesystem, no extra ops. Best for very
                        small installs and tests.

Both backends implement the same minimal protocol:

    save(name: str, content: bytes) -> str       # returns storage_key
    load(key: str) -> bytes
    delete(key: str) -> None

The *key* is opaque to callers — for ``local`` it's the relative path
under the storage root; for ``db`` it's an empty string (the row's
``datas`` is the source of truth and there's nothing else to address).

Sharding (local backend)
------------------------
Files land at::

    <root>/<aa>/<bb>/<uuid>_<safe-name>

where ``aa`` and ``bb`` are the first / second two hex characters of a
fresh UUID. Two levels of shards keep any single directory under a few
thousand entries even at millions of files. The UUID prefix on the
filename guarantees uniqueness without collision checks.

Out of scope for now
--------------------
* S3 / minio — easy to add (boto3 + presigned URL on ``url()``) once
  someone needs it.
* Background virus scan, content-addressable de-dup, lifecycle rules.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Protocol

from pyvelm.database import is_serverless_runtime


class StorageBackend(Protocol):
    """Minimal interface for blob storage."""

    def save(self, name: str, content: bytes) -> str: ...
    def load(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


# ---- safe filename helper ---------------------------------------------------

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize(name: str) -> str:
    """Trim to a printable, path-separator-free filename.

    The bytes are addressed by uuid prefix anyway — this is purely so a
    human inspecting the storage directory can recognise files. Empty /
    all-unsafe names fall back to ``file``."""
    cleaned = _UNSAFE.sub("_", (name or "").strip()) or "file"
    return cleaned[:120]  # arbitrary cap to keep paths sane


def _resolve_attachment_root(explicit: str | os.PathLike | None = None) -> Path:
    """Return a writable attachment directory for the current runtime."""
    if explicit is not None:
        return Path(explicit).resolve()

    env_root = os.environ.get("PYVELM_ATTACHMENT_DIR")
    path = Path(env_root or "./data/attachments")

    if is_serverless_runtime():
        # Vercel/Lambda only allow writes under /tmp — paths like /var/data
        # or ./data/attachments under the deployment bundle are read-only.
        resolved = path.resolve()
        if env_root and str(resolved).startswith("/tmp/"):
            return resolved
        return Path("/tmp/pyvelm-attachments").resolve()

    return path.resolve()


def _resolve_attachment_backend() -> str:
    """Pick ``local`` vs ``db`` — auto ``db`` on serverless + Postgres unless overridden."""
    explicit = (os.environ.get("PYVELM_ATTACHMENT_BACKEND") or "").strip().lower()
    if explicit:
        return explicit
    if is_serverless_runtime():
        try:
            from pyvelm.database import app_dsn_from_env, capabilities_from_dsn

            dsn = app_dsn_from_env()
            if dsn and capabilities_from_dsn(dsn).name == "postgresql":
                return "db"
        except Exception:
            pass
    return "local"


# ---- local filesystem backend ----------------------------------------------


class LocalStorageBackend:
    """Stores blobs under a sharded directory tree.

    The root directory is created on first ``save()``; ``load()`` and
    ``delete()`` rely on the caller passing back a key produced by
    ``save()``. ``delete()`` is best-effort — a missing key is a no-op
    (the row may have been hand-deleted; we don't want to fail an
    ORM unlink over filesystem noise)."""

    def __init__(self, root: str | os.PathLike | None = None) -> None:
        self.root = _resolve_attachment_root(root)

    def _full_path(self, key: str) -> Path:
        # Reject absolute / parent-escape keys — defence in depth even
        # though save() always emits relative paths.
        if os.path.isabs(key) or ".." in Path(key).parts:
            raise ValueError(f"Invalid storage key: {key!r}")
        return self.root / key

    def save(self, name: str, content: bytes) -> str:
        unique = uuid.uuid4().hex
        shard_a, shard_b = unique[:2], unique[2:4]
        safe = _sanitize(name)
        rel = Path(shard_a) / shard_b / f"{unique}_{safe}"
        abs_path = self.root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(content)
        return rel.as_posix()

    def load(self, key: str) -> bytes:
        return self._full_path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._full_path(key).unlink()
        except FileNotFoundError:
            return
        # Tidy empty shard dirs. Best-effort; we don't care if another
        # process raced us into adding a sibling.
        for parent in (self._full_path(key).parent,
                       self._full_path(key).parent.parent):
            if parent == self.root or not parent.exists():
                break
            try:
                parent.rmdir()
            except OSError:
                break


# ---- DB-only backend --------------------------------------------------------


class DbStorageBackend:
    """No-op backend — caller stores the bytes in the row's ``datas`` column.

    Useful for tests and tiny installs where the operator wants to keep
    everything in one place (pg_dump captures attachments). The
    backend itself holds nothing; ``load()`` always raises because the
    row's ``datas`` column is the source of truth."""

    def save(self, name: str, content: bytes) -> str:  # noqa: ARG002
        return ""  # empty key signals "row holds the bytes itself"

    def load(self, key: str) -> bytes:  # noqa: ARG002
        raise RuntimeError(
            "DbStorageBackend has no out-of-band bytes; read datas from the row."
        )

    def delete(self, key: str) -> None:  # noqa: ARG002
        return None


# ---- selector ---------------------------------------------------------------


_DEFAULT: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Return the process-wide backend selected by ``PYVELM_ATTACHMENT_BACKEND``.

    Cached so each request doesn't re-resolve the env var or
    re-instantiate the filesystem root path."""
    global _DEFAULT
    if _DEFAULT is not None:
        return _DEFAULT
    kind = _resolve_attachment_backend()
    if kind == "db":
        _DEFAULT = DbStorageBackend()
    elif kind == "local":
        _DEFAULT = LocalStorageBackend()
    else:
        raise RuntimeError(
            f"Unknown PYVELM_ATTACHMENT_BACKEND={kind!r}; "
            f"expected 'local' or 'db'."
        )
    return _DEFAULT


def reset_backend_cache() -> None:
    """Drop the cached backend so the next ``get_backend()`` re-reads env.

    Used by tests that flip ``PYVELM_ATTACHMENT_BACKEND`` mid-run."""
    global _DEFAULT
    _DEFAULT = None
