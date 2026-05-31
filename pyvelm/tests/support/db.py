"""Database helpers for integration tests (v1 SQLAlchemy layer).

All tests that touch a real database should go through this module instead of
calling ``psycopg.connect`` or ``ConnectionPool`` directly.

Integration tests use ``PYVELM_DSN_TEST`` only — never ``PYVELM_DSN``.
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Callable, Iterator, TypeVar

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.database import (
    ConnectionAdapter,
    Database,
    TEST_DSN_ENV,
    app_dsn_from_env,
    capabilities_from_dsn,
    create_database_from_dsn,
    delete_sqlite_file,
    normalize_dsn,
    test_dsn_from_env,
    to_psycopg_dsn,
)

DEFAULT_EXAMPLE_MODULES_ROOT = (
    Path(__file__).resolve().parents[3] / "examples" / "modules"
)
DEFAULT_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [DEFAULT_EXAMPLE_MODULES_ROOT]

_F = TypeVar("_F", bound=Callable)


def dsn_from_env() -> str | None:
    """Return the test database DSN (``PYVELM_DSN_TEST``)."""
    return test_dsn_from_env()


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
    """Skip when ``PYVELM_DSN_TEST`` is unset (pytest or unittest)."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not dsn_from_env():
            import pytest

            pytest.skip(f"{TEST_DSN_ENV} not set")
        return func(*args, **kwargs)

    wrapper.__unittest_skip__ = True  # type: ignore[attr-defined]
    wrapper.__unittest_skip_why__ = f"{TEST_DSN_ENV} not set"  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


def requires_backend(name: str) -> Callable[[_F], _F]:
    """Skip unless the test DSN targets *name* (``postgresql`` or ``sqlite``)."""

    def decorator(func: _F) -> _F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            dsn = dsn_from_env()
            if not dsn:
                raise unittest.SkipTest(f"{TEST_DSN_ENV} not set")
            if backend_name(dsn) != name:
                raise unittest.SkipTest(f"requires {name} backend")
            return func(*args, **kwargs)

        wrapper.__unittest_skip__ = True  # type: ignore[attr-defined]
        wrapper.__unittest_skip_why__ = f"requires {name} backend"  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


postgres_required = requires_backend("postgresql")


def _assert_safe_reset_dsn(dsn: str) -> None:
    """Refuse destructive resets against the application database."""
    app = app_dsn_from_env()
    if app and normalize_dsn(app) == normalize_dsn(dsn):
        raise RuntimeError(
            f"Refusing to reset {dsn!r} — it matches PYVELM_DSN. "
            f"Set {TEST_DSN_ENV} to a separate throwaway database for tests "
            "(see .env.testing.example)."
        )


def reset_database(dsn: str | None = None) -> None:
    """Wipe the test database so the next install starts from a clean slate.

    Close any open connections to *dsn* first — Postgres will block ``DROP
    TABLE`` while other sessions hold locks on those tables.
    """
    dsn = normalize_dsn(dsn or dsn_from_env() or "")
    _assert_safe_reset_dsn(dsn)
    cap = capabilities_from_dsn(dsn)
    if cap.name == "sqlite":
        delete_sqlite_file(dsn)
        return

    import psycopg

    with psycopg.connect(to_psycopg_dsn(dsn), autocommit=True) as conn:
        # Best-effort: same policy as terminate_other_backends (Supabase may
        # deny terminating superuser backends — ignore and continue).
        conn.execute(
            """
            DO $$
            DECLARE r RECORD;
            BEGIN
              FOR r IN
                SELECT pid FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND usename = current_user
              LOOP
                BEGIN
                  PERFORM pg_terminate_backend(r.pid);
                EXCEPTION WHEN OTHERS THEN
                  NULL;
                END;
              END LOOP;
            END $$;
            """
        )
        conn.execute("SET lock_timeout = '15s'")
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")


def open_database(dsn: str | None = None, *, pool_size: int = 2) -> Database:
    resolved = dsn or dsn_from_env()
    if not resolved:
        raise RuntimeError(f"{TEST_DSN_ENV} not set")
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


def install_named_modules(
    env: Environment,
    names: list[str],
    roots: list | None = None,
) -> None:
    """Install only *names* (and their dependencies) — not every bootstrap module."""
    from pyvelm.render import install_module_action

    roots = list(roots or DEFAULT_MODULE_ROOTS)
    with env.transaction():
        loader._ensure_ir_module(env)
    for name in names:
        install_module_action(env, roots, name)


class DatabaseTestCase(unittest.TestCase):
    """Base class for integration tests using :mod:`pyvelm.database`.

    Provides ``cls.dsn``, ``cls.database``, and ``cls.conn`` (an open
    :class:`~pyvelm.database.ConnectionAdapter`). Subclasses set up their own
    ``Registry`` / ``Environment`` in ``setUpClass``.

    Set ``fresh_db = True`` to wipe the test database before opening ``conn``
    (required when calling ``reset_database`` — never reset while a connection
    to the same DSN is still open).
    """

    required_backend: str | None = "postgresql"
    fresh_db: bool = False

    dsn: str
    database: Database
    conn: ConnectionAdapter

    @classmethod
    def setUpClass(cls) -> None:
        dsn = dsn_from_env()
        if not dsn:
            raise unittest.SkipTest(f"{TEST_DSN_ENV} not set")
        if cls.required_backend and backend_name(dsn) != cls.required_backend:
            raise unittest.SkipTest(
                f"requires {cls.required_backend} backend, got {backend_name(dsn)}"
            )
        cls.dsn = dsn
        cls.database = open_database(dsn, pool_size=2)
        if cls.fresh_db:
            reset_database(dsn)
        cls.conn = cls.database.open_connection()

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "conn", None) is not None:
            cls.conn.close()
        if getattr(cls, "database", None) is not None:
            cls.database.dispose()
