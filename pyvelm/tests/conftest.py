"""Pytest configuration and shared fixtures for pyvelm tests."""
from __future__ import annotations

import os

import pytest

from pyvelm.database import load_testing_env, normalize_dsn
from pyvelm.tests.support.db import (
    dsn_from_env,
    open_database,
    reset_database,
)


def pytest_configure(config) -> None:
    load_testing_env()
    for key in ("PYVELM_DSN_TEST", "PYVELM_DSN"):
        raw = os.environ.get(key)
        if raw:
            os.environ[key] = normalize_dsn(raw)


@pytest.fixture(scope="session")
def pyvelm_dsn() -> str:
    dsn = dsn_from_env()
    if not dsn:
        pytest.skip("PYVELM_DSN_TEST not set")
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
