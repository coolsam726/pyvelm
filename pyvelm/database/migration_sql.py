"""One-off module migration / admin SQL via SQLAlchemy ``text()``."""
from __future__ import annotations

from .adapter import ExecuteResult
from .sa_ddl import execute_sql


def execute_migration_sql(
    conn,
    sql: str,
    params: list | tuple | None = None,
) -> ExecuteResult:
    """Execute migration DDL/DML through the connection adapter."""
    return execute_sql(conn, sql, params)


def fetchone_migration(
    conn,
    sql: str,
    params: list | tuple | None = None,
) -> tuple | None:
    return execute_migration_sql(conn, sql, params).fetchone()


def fetchall_migration(
    conn,
    sql: str,
    params: list | tuple | None = None,
) -> list[tuple]:
    return execute_migration_sql(conn, sql, params).fetchall()
