"""PostgreSQL-specific schema wipe helpers."""
from __future__ import annotations

import os

from .adapter import ConnectionAdapter


def _uses_serverless_schema_wipe() -> bool:
    from pyvelm.database import uses_serverless_schema_wipe

    return uses_serverless_schema_wipe()


def terminate_other_backends(conn: ConnectionAdapter) -> None:
    if conn.capabilities.name != "postgresql":
        return
    try:
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
    except Exception:
        pass


def prepare_postgres_schema_drop(conn: ConnectionAdapter, schema: str) -> None:
    if conn.capabilities.name != "postgresql":
        return
    if _uses_serverless_schema_wipe():
        safe = (schema or "public").replace("'", "''")
        conn.execute(f"SELECT pg_advisory_lock(hashtext('pyvelm:wipe:{safe}'))")
        lock_timeout = (os.environ.get("PYVELM_NUKE_LOCK_TIMEOUT") or "120s").strip()
    else:
        terminate_other_backends(conn)
        lock_timeout = (os.environ.get("PYVELM_NUKE_LOCK_TIMEOUT") or "15s").strip()
    conn.execute(f"SET lock_timeout = '{lock_timeout or '15s'}'")
    conn.execute("SET statement_timeout = '300s'")


def release_postgres_schema_drop_lock(conn: ConnectionAdapter, schema: str) -> None:
    if conn.capabilities.name != "postgresql" or not _uses_serverless_schema_wipe():
        return
    safe = (schema or "public").replace("'", "''")
    conn.execute(f"SELECT pg_advisory_unlock(hashtext('pyvelm:wipe:{safe}'))")
