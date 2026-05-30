"""SQLAlchemy-backed database engine, pool, and psycopg-compatible connection adapter.

v1.x portability layer — see docs/multi-database.md and docs/adr/001-sqlalchemy-core.md.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool


class SchemaResetStrategy(str, Enum):
    DROP_SCHEMA = "drop_schema"
    DROP_ALL_TABLES = "drop_all_tables"
    DELETE_FILE = "delete_file"


@dataclass(frozen=True)
class DialectCapabilities:
    """Backend feature flags used by ORM, domain, and migrate helpers."""

    name: str
    supports_returning: bool
    supports_ilike: bool
    supports_add_column_if_not_exists: bool
    supports_drop_schema: bool
    schema_reset: SchemaResetStrategy
    placeholder: str  # ``%s`` (postgres/psycopg) or ``?`` (sqlite)


def normalize_dsn(dsn: str) -> str:
    """Normalise legacy DSNs to SQLAlchemy URL form."""
    dsn = (dsn or "").strip()
    if not dsn:
        raise ValueError("DSN is empty")
    if dsn.startswith("postgres://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgres://") :]
    elif dsn.startswith("postgresql://") and "+psycopg" not in dsn.split(":", 1)[0]:
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://") :]
    return dsn


def to_psycopg_dsn(dsn: str) -> str:
    """Return a libpq/psycopg connection string from a SQLAlchemy URL."""
    normalized = normalize_dsn(dsn)
    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "").split("+", 1)[0].lower()
    if scheme not in ("postgresql", "postgres"):
        raise ValueError(
            f"to_psycopg_dsn expects a PostgreSQL URL, got scheme {scheme!r}"
        )
    netloc = parsed.netloc
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"postgresql://{netloc}{path}{query}"


def dialect_capabilities(dialect_name: str) -> DialectCapabilities:
    name = (dialect_name or "postgresql").split("+", 1)[0].lower()
    if name == "sqlite":
        return DialectCapabilities(
            name="sqlite",
            supports_returning=True,
            supports_ilike=False,
            supports_add_column_if_not_exists=False,
            supports_drop_schema=False,
            schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
            placeholder="?",
        )
    return DialectCapabilities(
        name="postgresql",
        supports_returning=True,
        supports_ilike=True,
        supports_add_column_if_not_exists=True,
        supports_drop_schema=True,
        schema_reset=SchemaResetStrategy.DROP_SCHEMA,
        placeholder="%s",
    )


def capabilities_from_dsn(dsn: str) -> DialectCapabilities:
    parsed = urlparse(normalize_dsn(dsn))
    scheme = (parsed.scheme or "").split("+", 1)[0].lower()
    return dialect_capabilities(scheme)


class ExecuteResult:
    """Minimal cursor-like result for ``conn.execute`` call sites."""

    __slots__ = ("_rows", "_rowcount")

    def __init__(self, rows: list[tuple] | None = None, rowcount: int = -1) -> None:
        self._rows = rows
        self._rowcount = rowcount

    def fetchall(self) -> list[tuple]:
        if self._rows is not None:
            return list(self._rows)
        return []

    def fetchone(self) -> tuple | None:
        if self._rows is not None:
            return self._rows[0] if self._rows else None
        return None

    @property
    def rowcount(self) -> int:
        return self._rowcount


class ConnectionAdapter:
    """Psycopg-shaped connection wrapper over SQLAlchemy / DBAPI."""

    def __init__(
        self,
        sa_conn,
        *,
        capabilities: DialectCapabilities,
        dbapi_conn=None,
        owns_sa: bool = True,
    ) -> None:
        self._sa = sa_conn
        self._dbapi = dbapi_conn
        self.capabilities = capabilities
        self.dialect_name = capabilities.name
        self._autocommit = False
        self._in_tx = False
        self.owns_sa = owns_sa

    @classmethod
    def from_sa_connection(cls, sa_conn, capabilities: DialectCapabilities) -> ConnectionAdapter:
        dbapi = getattr(getattr(sa_conn, "connection", None), "dbapi_connection", None)
        if dbapi is None:
            dbapi = getattr(sa_conn, "dbapi_connection", None)
        return cls(sa_conn, capabilities=capabilities, dbapi_conn=dbapi)

    @property
    def autocommit(self) -> bool:
        if self._dbapi is not None and hasattr(self._dbapi, "autocommit"):
            return bool(self._dbapi.autocommit)
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self._autocommit = bool(value)
        if self._dbapi is not None and hasattr(self._dbapi, "autocommit"):
            self._dbapi.autocommit = bool(value)

    def _convert_sql(self, sql: str) -> str:
        if self.capabilities.placeholder == "%s":
            return sql
        if "%s" not in sql:
            return sql
        return sql.replace("%s", "?")

    def execute(self, sql: str, params: list | tuple | None = None) -> ExecuteResult:
        sql = self._convert_sql(sql)
        if params is not None:
            bind = tuple(params)
            result = self._sa.exec_driver_sql(sql, bind)
        else:
            result = self._sa.exec_driver_sql(sql)
        rows = None
        if result.returns_rows:
            rows = [tuple(row) for row in result.fetchall()]
        return ExecuteResult(rows=rows, rowcount=result.rowcount)

    def commit(self) -> None:
        if self._dbapi is not None and hasattr(self._dbapi, "commit"):
            self._dbapi.commit()
        elif self._sa is not None:
            self._sa.commit()
        self._in_tx = False

    def rollback(self) -> None:
        if self._dbapi is not None and hasattr(self._dbapi, "rollback"):
            self._dbapi.rollback()
        elif self._sa is not None:
            self._sa.rollback()
        self._in_tx = False

    def close(self) -> None:
        if self._sa is not None and self.owns_sa:
            self._sa.close()


class PoolFacade:
    """Drop-in for ``psycopg_pool.ConnectionPool.connection()``."""

    def __init__(self, database: Database) -> None:
        self._database = database

    @contextmanager
    def connection(self) -> Iterator[ConnectionAdapter]:
        with self._database.checkout() as conn:
            yield conn


class Database:
    """Process-scoped database handle (one DSN). v1.1 may map many Database instances."""

    def __init__(
        self,
        engine: Engine,
        *,
        dsn: str,
        capabilities: DialectCapabilities,
        pool_size: int = 4,
    ) -> None:
        self.engine = engine
        self.dsn = dsn
        self.capabilities = capabilities
        self.pool_size = pool_size
        self.pool = PoolFacade(self)

    @classmethod
    def from_dsn(
        cls,
        dsn: str,
        *,
        pool_size: int = 4,
        echo: bool = False,
    ) -> Database:
        normalized = normalize_dsn(dsn)
        caps = capabilities_from_dsn(normalized)
        kwargs: dict[str, Any] = {"echo": echo}
        if caps.name == "sqlite":
            # SQLite: allow use from multiple threads in dev/tests (one process).
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = QueuePool
            kwargs["pool_size"] = pool_size
            kwargs["max_overflow"] = 0
        else:
            kwargs["pool_size"] = pool_size
            kwargs["max_overflow"] = 0
        engine = create_engine(normalized, **kwargs)
        return cls(engine, dsn=normalized, capabilities=caps, pool_size=pool_size)

    @contextmanager
    def connect(self) -> Iterator[ConnectionAdapter]:
        """One-shot connection for boot / migrate (autocommit)."""
        with self.engine.connect() as sa_conn:
            adapter = ConnectionAdapter.from_sa_connection(sa_conn, self.capabilities)
            adapter.autocommit = True
            try:
                yield adapter
            finally:
                adapter.close()

    @contextmanager
    def checkout(self) -> Iterator[ConnectionAdapter]:
        """Pooled request-scoped connection."""
        with self.engine.connect() as sa_conn:
            adapter = ConnectionAdapter.from_sa_connection(sa_conn, self.capabilities)
            adapter.autocommit = True
            try:
                yield adapter
            finally:
                adapter.close()

    def open_connection(self) -> ConnectionAdapter:
        """Open a connection the caller must ``close()`` (CLI one-shots)."""
        sa_conn = self.engine.connect()
        adapter = ConnectionAdapter.from_sa_connection(sa_conn, self.capabilities)
        adapter.autocommit = True
        adapter.owns_sa = True
        return adapter

    def inspector(self):
        return inspect(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def create_database_from_dsn(dsn: str, *, pool_size: int = 4) -> Database:
    return Database.from_dsn(dsn, pool_size=pool_size)


def require_dsn_from_env() -> str:
    import os

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        raise SystemExit("PYVELM_DSN not set")
    return dsn


def dsn_display(dsn: str) -> str:
    """Return a DSN safe to print (password redacted)."""
    try:
        parsed = urlparse(normalize_dsn(dsn))
        if parsed.scheme and parsed.hostname:
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:***@{netloc}"
            path = parsed.path or ""
            return urlunparse((parsed.scheme, netloc, path, parsed.params, "", ""))
    except Exception:
        pass
    return "<dsn>"


# ---- DDL / DML dialect helpers (used by model.py, domain.py, migrate_cli) ----


def serial_primary_key(cap: DialectCapabilities) -> str:
    if cap.name == "sqlite":
        return '"id" INTEGER PRIMARY KEY AUTOINCREMENT'
    return '"id" SERIAL PRIMARY KEY'


def returning_id_clause(cap: DialectCapabilities) -> str:
    if cap.name == "sqlite" and cap.supports_returning:
        return ' RETURNING "id"'
    if cap.supports_returning:
        return ' RETURNING "id"'
    return ""


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    row = conn.execute(f'SELECT MAX("id") FROM "{table}"').fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def ilike_sql(column_sql: str, cap: DialectCapabilities) -> str:
    if cap.supports_ilike:
        return f"{column_sql} ILIKE %s"
    return f"LOWER({column_sql}) LIKE LOWER(%s)"


def add_column_if_not_exists_sql(
    table: str, column: str, sql_type: str, cap: DialectCapabilities
) -> str | None:
    if cap.supports_add_column_if_not_exists:
        return (
            f'ALTER TABLE "{table}" '
            f'ADD COLUMN IF NOT EXISTS "{column}" {sql_type}'
        )
    return None


def column_exists(conn, table: str, column: str, cap: DialectCapabilities | None = None) -> bool:
    """Return whether ``column`` exists on ``table``."""
    cap = cap or _conn_capabilities(conn)
    if not table_exists(conn, table, cap):
        return False
    if cap.name == "sqlite":
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        return column in {r[1] for r in rows}
    if hasattr(conn, "_sa") and conn._sa is not None:
        from sqlalchemy import inspect as sa_inspect

        cols = sa_inspect(conn._sa.engine).get_columns(table)
        return column in {c["name"] for c in cols}
    rows = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()
    return row is not None


def add_column_if_missing(
    conn,
    table: str,
    column: str,
    sql_type: str,
    cap: DialectCapabilities | None = None,
) -> bool:
    """Add a column when absent; return True if DDL was executed."""
    cap = cap or _conn_capabilities(conn)
    if column_exists(conn, table, column, cap):
        return False
    stmt = add_column_if_not_exists_sql(table, column, sql_type, cap)
    if stmt is None:
        stmt = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {sql_type}'
    try:
        conn.execute(stmt)
    except Exception as exc:
        orig = getattr(exc, "orig", exc)
        if cap.name == "sqlite" and "duplicate column" in str(orig).lower():
            return False
        raise
    return True


def reset_schema(conn: ConnectionAdapter, cap: DialectCapabilities) -> None:
    """Backend-specific schema wipe for migrate:reset / migrate:fresh."""
    if cap.schema_reset == SchemaResetStrategy.DROP_SCHEMA:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("GRANT ALL ON SCHEMA public TO public")
        return

    if cap.schema_reset == SchemaResetStrategy.DROP_ALL_TABLES:
        engine = conn._sa.engine
        insp = inspect(engine)
        for table in insp.get_table_names():
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        return

    raise RuntimeError(f"Unsupported schema reset for dialect {cap.name!r}")


def migration_supported(
    env_conn: ConnectionAdapter, supported_backends: tuple[str, ...] | None
) -> bool:
    """Return whether a hand-written migration should run on this connection."""
    if not supported_backends:
        supported_backends = ("postgresql",)
    return env_conn.dialect_name in supported_backends


def sqlite_file_path(dsn: str) -> str | None:
    parsed = urlparse(normalize_dsn(dsn))
    if parsed.scheme.split("+", 1)[0].lower() != "sqlite":
        return None
    path = (parsed.path or "").lstrip("/")
    if parsed.netloc:
        path = f"/{parsed.netloc}/{path}" if path else f"/{parsed.netloc}"
    elif path and not path.startswith("/"):
        path = str(__import__("pathlib").Path(path).resolve())
    return path or None


def delete_sqlite_file(dsn: str) -> None:
    path = sqlite_file_path(dsn)
    if path:
        import os
        from pathlib import Path

        p = Path(path)
        if p.is_file():
            os.remove(p)


def _conn_capabilities(conn) -> DialectCapabilities:
    cap = getattr(conn, "capabilities", None)
    if cap is not None:
        return cap
    name = getattr(conn, "dialect_name", None)
    if name:
        return dialect_capabilities(name)
    return dialect_capabilities("postgresql")


def timestamp_sql_type(cap: DialectCapabilities) -> str:
    return "timestamp" if cap.name == "sqlite" else "timestamptz"


def now_sql(cap: DialectCapabilities) -> str:
    return "CURRENT_TIMESTAMP" if cap.name == "sqlite" else "now()"


def normalize_sql_type(type_spec: str, cap: DialectCapabilities) -> str:
    """Map Postgres-oriented field types to the active dialect."""
    if cap.name != "sqlite":
        return type_spec
    mapping = {
        "double precision": "REAL",
        "timestamptz": "timestamp",
        "SERIAL": "INTEGER",
    }
    out = type_spec
    for src, dst in mapping.items():
        out = out.replace(src, dst)
    return out


def normalize_column_ddl(ddl: str, cap: DialectCapabilities) -> str:
    if cap.name != "sqlite":
        return ddl
    out = ddl
    for src, dst in (
        ("double precision", "REAL"),
        ("timestamptz", "timestamp"),
        ("SERIAL", "INTEGER"),
    ):
        out = out.replace(src, dst)
    return out


def ir_module_create_sql(cap: DialectCapabilities) -> str:
    ts = timestamp_sql_type(cap)
    default = now_sql(cap)
    return (
        f'CREATE TABLE IF NOT EXISTS "ir_module" ('
        f'"name" text PRIMARY KEY, '
        f'"version" text NOT NULL, '
        f'"installed_at" {ts} NOT NULL DEFAULT {default})'
    )


def table_exists(conn, table: str, cap: DialectCapabilities | None = None) -> bool:
    cap = cap or _conn_capabilities(conn)
    if cap.name == "sqlite":
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = %s",
            (table,),
        ).fetchone()
        return row is not None
    if hasattr(conn, "_sa") and conn._sa is not None:
        from sqlalchemy import inspect as sa_inspect

        return sa_inspect(conn._sa.engine).has_table(table)
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None
