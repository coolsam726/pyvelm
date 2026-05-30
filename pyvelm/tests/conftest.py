"""Pytest configuration and shared fixtures for pyvelm tests."""
from __future__ import annotations

import os

import pytest

from pyvelm.tests.support.db import (
    dsn_from_env,
    open_database,
    reset_database,
)


def pytest_configure(config) -> None:
    raw = os.environ.get("PYVELM_DSN")
    if raw:
        from pyvelm.database import normalize_dsn

        os.environ["PYVELM_DSN"] = normalize_dsn(raw)


@pytest.fixture(scope="session")
def pyvelm_dsn() -> str:
    dsn = dsn_from_env()
    if not dsn:
        pytest.skip("PYVELM_DSN not set")
    return dsn


@pytest.fixture(scope="session")
def db_backend(pyvelm_dsn: str) -> str:
    from pyvelm.database import capabilities_from_dsn

    return capabilities_from_dsn(pyvelm_dsn).name


@pytest.fixture(scope="session")
def database(pyvelm_dsn: str):
    db = open_database(pyvelm_dsn, pool_size=4)
    yield db
    db.dispose()


@pytest.fixture
def db_conn(database):
    """One autocommit connection per test (function scope)."""
    conn = database.open_connection()
    try:
        yield conn
    finally:
        conn.close()


# Backward-compatible alias used by older tests.
reset_public_schema = reset_database
