"""Shared pytest helpers for integration tests."""
from __future__ import annotations

import os

import pytest


def reset_public_schema(dsn: str) -> None:
    """Drop every table in ``public`` so installs start from a clean slate."""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        for (name,) in rows:
            conn.execute(f'DROP TABLE IF EXISTS public."{name}" CASCADE')


@pytest.fixture(scope="session")
def pyvelm_dsn() -> str:
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        pytest.skip("PYVELM_DSN not set")
    return dsn
