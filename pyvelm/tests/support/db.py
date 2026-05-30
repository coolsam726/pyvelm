"""Database helpers for integration tests (v1 SQLAlchemy layer).

All tests that touch a real database should go through this module instead of
calling ``psycopg.connect`` or ``ConnectionPool`` directly.
"""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.database import (
    ConnectionAdapter,
    Database,
    capabilities_from_dsn,
    create_database_from_dsn,
    delete_sqlite_file,
    normalize_dsn,
    to_psycopg_dsn,
)

DEFAULT_EXAMPLE_MODULES_ROOT = (
    Path(__file__).resolve().parents[3] / "examples" / "modules"
)
DEFAULT_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [DEFAULT_EXAMPLE_MODULES_ROOT]

_F = TypeVar("_F", bound=Callable)


def dsn_from_env() -> str | None:
    raw = os.environ.get("PYVELM_DSN")
    if not raw:
        return None
    return normalize_dsn(raw)


def backend_name(dsn: str | None = None) -> str | None:
    dsn = dsn or dsn_from_env()
    if not dsn:
        return None
    return capabilities_from_dsn(dsn).name


def is_postgres(dsn: str | None = None) -> bool:
    return backend_name(dsn) == "postgresql"


def is_sqlite(dsn: str | None = None) -> bool:
    return backend_name(dsn) == "sqlite"


def requires_dsn(func: _F) -> _F:
    """Skip when ``PYVELM_DSN`` is unset (pytest or unittest)."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not dsn_from_env():
            import pytest

            pytest.skip("PYVELM_DSN not set")
        return func(*args, **kwargs)

    wrapper.__unittest_skip__ = True  # type: ignore[attr-defined]
    wrapper.__unittest_skip_why__ = "PYVELM_DSN not set"  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


def requires_backend(name: str) -> Callable[[_F], _F]:
    """Skip unless ``PYVELM_DSN`` targets *name* (``postgresql`` or ``sqlite``)."""

    def decorator(func: _F) -> _F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            dsn = dsn_from_env()
            if not dsn:
                raise unittest.SkipTest("PYVELM_DSN not set")
            if backend_name(dsn) != name:
                raise unittest.SkipTest(f"requires {name} backend")
            return func(*args, **kwargs)

        wrapper.__unittest_skip__ = True  # type: ignore[attr-defined]
        wrapper.__unittest_skip_why__ = f"requires {name} backend"  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


postgres_required = requires_backend("postgresql")


def reset_database(dsn: str | None = None) -> None:
    """Wipe the database so the next install starts from a clean slate."""
    dsn = normalize_dsn(dsn or dsn_from_env() or "")
    cap = capabilities_from_dsn(dsn)
    if cap.name == "sqlite":
        delete_sqlite_file(dsn)
        return

    import psycopg

    with psycopg.connect(to_psycopg_dsn(dsn), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        for (name,) in rows:
            conn.execute(f'DROP TABLE IF EXISTS public."{name}" CASCADE')


def open_database(dsn: str | None = None, *, pool_size: int = 2) -> Database:
    resolved = dsn or dsn_from_env()
    if not resolved:
        raise RuntimeError("PYVELM_DSN not set")
    return create_database_from_dsn(normalize_dsn(resolved), pool_size=pool_size)


@contextmanager
def db_connection(dsn: str | None = None) -> Iterator[ConnectionAdapter]:
    db = open_database(dsn)
    try:
        with db.connect() as conn:
            yield conn
    finally:
        db.dispose()


@contextmanager
def test_env(
    dsn: str | None = None,
    *,
    uid: int | None = 1,
    acl_bypass: bool = False,
    registry: Registry | None = None,
) -> Iterator[Environment]:
    reg = registry or Registry()
    with db_connection(dsn) as conn:
        env = Environment(conn, registry=reg, uid=uid)
        if acl_bypass:
            env._acl_bypass = True
        yield env


def install_modules(
    env: Environment,
    roots: list | None = None,
    *,
    install_all: bool = False,
):
    roots = list(roots or DEFAULT_MODULE_ROOTS)
    return loader.load_and_install(roots, env, install_all=install_all)


class DatabaseTestCase(unittest.TestCase):
    """Base class for integration tests using :mod:`pyvelm.database`.

    Provides ``cls.dsn``, ``cls.database``, and ``cls.conn`` (an open
    :class:`~pyvelm.database.ConnectionAdapter`). Subclasses set up their own
    ``Registry`` / ``Environment`` in ``setUpClass``.
    """

    required_backend: str | None = "postgresql"

    dsn: str
    database: Database
    conn: ConnectionAdapter

    @classmethod
    def setUpClass(cls) -> None:
        dsn = dsn_from_env()
        if not dsn:
            raise unittest.SkipTest("PYVELM_DSN not set")
        if cls.required_backend and backend_name(dsn) != cls.required_backend:
            raise unittest.SkipTest(
                f"requires {cls.required_backend} backend, got {backend_name(dsn)}"
            )
        cls.dsn = dsn
        cls.database = open_database(dsn, pool_size=2)
        cls.conn = cls.database.open_connection()

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "conn", None) is not None:
            cls.conn.close()
        if getattr(cls, "database", None) is not None:
            cls.database.dispose()
