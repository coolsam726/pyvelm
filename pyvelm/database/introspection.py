"""Schema introspection helpers."""
from __future__ import annotations

from sqlalchemy.engine import Connection as SAConnection

from .adapter import conn_capabilities, sqlalchemy_connection
from .capabilities import DialectCapabilities


def _inspector_sa_connection(sa_conn) -> SAConnection | None:
    if isinstance(sa_conn, SAConnection):
        return sa_conn
    return None


def column_exists(
    conn, table: str, column: str, cap: DialectCapabilities | None = None
) -> bool:
    cap = cap or conn_capabilities(conn)
    if not table_exists(conn, table, cap):
        return False
    if cap.name == "sqlite":
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return column in {r[1] for r in rows}
    sa_conn = _inspector_sa_connection(sqlalchemy_connection(conn))
    if sa_conn is not None:
        from sqlalchemy import inspect as sa_inspect

        cols = sa_inspect(sa_conn).get_columns(table)
        return column in {c["name"] for c in cols}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchall()
    return column in {r[0] for r in rows}


def table_exists(conn, table: str, cap: DialectCapabilities | None = None) -> bool:
    cap = cap or conn_capabilities(conn)
    if cap.name == "sqlite":
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = %s",
            (table,),
        ).fetchone()
        return row is not None
    sa_conn = _inspector_sa_connection(sqlalchemy_connection(conn))
    if sa_conn is not None:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import NoSuchTableError

        try:
            return sa_inspect(sa_conn).has_table(table)
        except NoSuchTableError:
            return False
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None
