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
from sqlalchemy.engine import Connection as SAConnection
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


def _dialect_base_name(dialect_name: str) -> str:
    """Normalise SQLAlchemy dialect names to pyvelm capability keys."""
    name = (dialect_name or "postgresql").split("+", 1)[0].lower()
    if name in ("mariadb", "mysql"):
        return "mysql"
    if name in ("mssql", "sqlserver"):
        return "mssql"
    return name


def normalize_dsn(dsn: str) -> str:
    """Normalise legacy DSNs to SQLAlchemy URL form."""
    dsn = (dsn or "").strip()
    if not dsn:
        raise ValueError("DSN is empty")
    if dsn.startswith("postgres://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgres://") :]
    elif dsn.startswith("postgresql://") and "+psycopg" not in dsn.split(":", 1)[0]:
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://") :]
    elif dsn.startswith("mysql://") and "+pymysql" not in dsn.split(":", 1)[0]:
        dsn = "mysql+pymysql://" + dsn[len("mysql://") :]
    elif dsn.startswith("mariadb://") and "+pymysql" not in dsn.split(":", 1)[0]:
        dsn = "mariadb+pymysql://" + dsn[len("mariadb://") :]
    elif dsn.startswith("mssql://") and "+pyodbc" not in dsn.split(":", 1)[0]:
        dsn = "mssql+pyodbc://" + dsn[len("mssql://") :]
    elif dsn.startswith("sqlserver://") and "+pyodbc" not in dsn.split(":", 1)[0]:
        dsn = "mssql+pyodbc://" + dsn[len("sqlserver://") :]
    elif dsn.startswith("oracle://") and "+oracledb" not in dsn.split(":", 1)[0]:
        dsn = "oracle+oracledb://" + dsn[len("oracle://") :]
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
    name = _dialect_base_name(dialect_name)
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
    if name == "mysql":
        return DialectCapabilities(
            name="mysql",
            supports_returning=False,
            supports_ilike=False,
            supports_add_column_if_not_exists=False,
            supports_drop_schema=False,
            schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
            placeholder="%s",
        )
    if name == "mssql":
        return DialectCapabilities(
            name="mssql",
            supports_returning=False,
            supports_ilike=False,
            supports_add_column_if_not_exists=False,
            supports_drop_schema=False,
            schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
            placeholder="%s",
        )
    if name == "oracle":
        return DialectCapabilities(
            name="oracle",
            supports_returning=True,
            supports_ilike=False,
            supports_add_column_if_not_exists=False,
            supports_drop_schema=False,
            schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
            placeholder="%s",
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


def _configure_engine(engine: Engine, caps: DialectCapabilities) -> None:
    """Dialect-specific engine hooks (MySQL ``ANSI_QUOTES`` for quoted identifiers)."""
    from sqlalchemy import event

    if caps.name == "mysql":

        @event.listens_for(engine, "connect")
        def _mysql_on_connect(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET SESSION sql_mode = 'ANSI_QUOTES'")
            cursor.close()

    if caps.name == "mssql":

        @event.listens_for(engine, "connect")
        def _mssql_on_connect(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET QUOTED_IDENTIFIER ON")
            cursor.close()


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
            bind = _bind_params(tuple(params), self.capabilities)
            result = self._sa.exec_driver_sql(sql, bind)
        else:
            result = self._sa.exec_driver_sql(sql)
        rows = None
        if result.returns_rows:
            rows = [tuple(row) for row in result.fetchall()]
        return ExecuteResult(rows=rows, rowcount=result.rowcount)

    def commit(self) -> None:
        if self._sa is not None:
            self._sa.commit()
        elif self._dbapi is not None and hasattr(self._dbapi, "commit"):
            self._dbapi.commit()
        self._in_tx = False

    def rollback(self) -> None:
        if self._sa is not None:
            self._sa.rollback()
        elif self._dbapi is not None and hasattr(self._dbapi, "rollback"):
            self._dbapi.rollback()
        self._in_tx = False

    def close(self) -> None:
        if self._sa is not None and self.owns_sa:
            # SQLAlchemy 2 autobegin opens a transaction even when DBAPI
            # autocommit is True (MySQL/MariaDB). Commit pending work before
            # close so boot/migrate one-shots persist across pool checkouts.
            if self.autocommit:
                try:
                    self.commit()
                except Exception:
                    try:
                        self.rollback()
                    except Exception:
                        pass
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
    """Process-scoped database handle (one DSN). Multi-DB routing may map many instances."""

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
        normalized = resolve_sqlite_dsn_for_runtime(normalized)
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
        _configure_engine(engine, caps)
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


def uses_serverless_schema_wipe() -> bool:
    """True when schema wipe needs serverless/managed-Postgres hardening."""
    import os

    if is_serverless_runtime():
        return True
    flag = (os.environ.get("PYVELM_NUKE_SERVERLESS") or "").strip().lower()
    return flag in ("1", "true", "yes", "on")


def nuke_dsn_from_env() -> str:
    """DSN for ``db nuke`` — ``PYVELM_NUKE_DSN`` when set, else ``PYVELM_DSN``."""
    import os

    raw = (os.environ.get("PYVELM_NUKE_DSN") or os.environ.get("PYVELM_DSN") or "").strip()
    if not raw:
        raise SystemExit("PYVELM_DSN not set")
    return normalize_dsn(raw)


def is_transaction_pooler_dsn(dsn: str) -> bool:
    """True for pgBouncer *transaction* mode (Supabase port 6543)."""
    try:
        parsed = urlparse(normalize_dsn(dsn))
        if parsed.port == 6543:
            return True
    except Exception:
        pass
    return ":6543" in (dsn or "")


def is_supabase_direct_host(dsn: str) -> bool:
    """True when the host is Supabase's direct ``db.<ref>.supabase.co`` endpoint."""
    try:
        parsed = urlparse(normalize_dsn(dsn))
        host = (parsed.hostname or "").lower()
        return host.startswith("db.") and host.endswith(".supabase.co")
    except Exception:
        return False


def warn_if_poor_nuke_dsn(dsn: str) -> None:
    """Emit stderr hints when a schema wipe DSN is likely to fail (serverless only)."""
    if not uses_serverless_schema_wipe():
        return
    import sys

    if is_transaction_pooler_dsn(dsn):
        print(
            "WARNING: Schema wipe through a transaction pooler (port 6543) can "
            "deadlock. Use a session pooler URL (port 5432) for PYVELM_NUKE_DSN.",
            file=sys.stderr,
        )
        return
    if is_supabase_direct_host(dsn):
        print(
            "WARNING: Supabase direct host db.*.supabase.co is often IPv6-only "
            "from serverless builders. Use *.pooler.supabase.com:5432 instead.",
            file=sys.stderr,
        )


def terminate_other_backends(conn: ConnectionAdapter) -> None:
    """Best-effort terminate of other sessions owned by ``current_user``.

    Helps before ``DROP SCHEMA`` when warm app instances still hold locks.
    On managed Postgres (Supabase) terminating superuser-owned backends raises
    ``InsufficientPrivilege`` — those failures are ignored so the wipe can
    proceed (advisory lock + ``lock_timeout`` handle the rest).
    """
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
    """Prepare session settings before ``DROP SCHEMA … CASCADE``."""
    if conn.capabilities.name != "postgresql":
        return
    import os

    if uses_serverless_schema_wipe():
        safe = (schema or "public").replace("'", "''")
        conn.execute(f"SELECT pg_advisory_lock(hashtext('pyvelm:wipe:{safe}'))")
        lock_timeout = (os.environ.get("PYVELM_NUKE_LOCK_TIMEOUT") or "120s").strip()
    else:
        terminate_other_backends(conn)
        lock_timeout = (os.environ.get("PYVELM_NUKE_LOCK_TIMEOUT") or "15s").strip()
    conn.execute(f"SET lock_timeout = '{lock_timeout or '15s'}'")
    conn.execute("SET statement_timeout = '300s'")


def release_postgres_schema_drop_lock(conn: ConnectionAdapter, schema: str) -> None:
    if conn.capabilities.name != "postgresql" or not uses_serverless_schema_wipe():
        return
    safe = (schema or "public").replace("'", "''")
    conn.execute(f"SELECT pg_advisory_unlock(hashtext('pyvelm:wipe:{safe}'))")


TEST_DSN_ENV = "PYVELM_DSN_TEST"


def load_testing_env() -> bool:
    """Load ``.env.testing`` when present (Laravel-style test overrides).

    Uses ``override=True`` so test variables win over values already loaded
    from ``.env``. Returns ``True`` when a file was loaded.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return False
    path = find_dotenv(".env.testing", usecwd=True)
    if not path:
        return False
    load_dotenv(path, override=True)
    return True


def test_dsn_from_env() -> str | None:
    import os

    raw = os.environ.get(TEST_DSN_ENV)
    if not raw:
        return None
    return normalize_dsn(raw)


def require_test_dsn_from_env() -> str:
    dsn = test_dsn_from_env()
    if not dsn:
        raise SystemExit(
            f"{TEST_DSN_ENV} not set — configure a throwaway database for tests "
            "(copy .env.testing.example to .env.testing)."
        )
    return dsn


def app_dsn_from_env() -> str | None:
    """Application DSN from ``PYVELM_DSN`` (not used by the test suite)."""
    import os

    raw = os.environ.get("PYVELM_DSN")
    if not raw:
        return None
    return normalize_dsn(raw)


def dsn_display(dsn: str) -> str:
    """Return a DSN safe to print (password redacted)."""
    try:
        parsed = urlparse(normalize_dsn(dsn))
        scheme = (parsed.scheme or "").split("+", 1)[0].lower()
        if scheme == "sqlite":
            path = parsed.path or ""
            if parsed.netloc:
                path = f"/{parsed.netloc}{path}"
            return f"sqlite://{path or ':memory:'}"
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
    if cap.name == "mysql":
        return '"id" INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY'
    if cap.name == "mssql":
        return '"id" INTEGER NOT NULL IDENTITY(1,1) PRIMARY KEY'
    if cap.name == "oracle":
        return '"id" INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY'
    return '"id" SERIAL PRIMARY KEY'


def returning_id_clause(cap: DialectCapabilities) -> str:
    if cap.name == "sqlite" and cap.supports_returning:
        return ' RETURNING "id"'
    if cap.supports_returning:
        return ' RETURNING "id"'
    return ""


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    cap = _conn_capabilities(conn)
    if cap.name == "mysql":
        row = conn.execute("SELECT LAST_INSERT_ID()").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    if cap.name == "mssql":
        row = conn.execute("SELECT CAST(SCOPE_IDENTITY() AS INTEGER)").fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    row = conn.execute(f'SELECT MAX("id") FROM "{table}"').fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def append_search_pagination(
    sql: str,
    *,
    base_table_sql: str,
    limit: int | None,
    offset: int,
    order: str | None,
    cap: DialectCapabilities,
) -> str:
    """Append ``LIMIT``/``OFFSET`` or T-SQL/Oracle ``OFFSET … FETCH``."""
    if limit is None and not offset:
        return sql
    if cap.name in ("postgresql", "mysql", "sqlite"):
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"
        return sql
    if " ORDER BY " not in sql.upper():
        if order:
            sql += f" ORDER BY {order}"
        else:
            sql += f' ORDER BY {base_table_sql}."id"'
    sql += f" OFFSET {int(offset)} ROWS"
    if limit is not None:
        sql += f" FETCH NEXT {int(limit)} ROWS ONLY"
    return sql


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
    sa_conn = _sqlalchemy_connection(conn)
    if sa_conn is not None:
        from sqlalchemy import inspect as sa_inspect

        # Inspect via the LIVE connection, not the engine. Inspecting the
        # engine checks out a *second* pooled connection, which deadlocks
        # on Postgres when this one holds an uncommitted ALTER TABLE (an
        # ACCESS EXCLUSIVE lock the new connection can never acquire).
        cols = sa_inspect(sa_conn).get_columns(table)
        return column in {c["name"] for c in cols}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchall()
    return column in {r[0] for r in rows}


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
        msg = str(orig).lower()
        if cap.name == "sqlite" and "duplicate column" in msg:
            return False
        if cap.name == "mysql" and "duplicate column" in msg:
            return False
        if cap.name == "mssql" and (
            "duplicate column" in msg or "already an object named" in msg
        ):
            return False
        if cap.name == "oracle" and (
            "already exists" in msg or "name is already used" in msg
        ):
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
        if cap.name == "mysql":
            conn.execute("SET FOREIGN_KEY_CHECKS = 0")
        if cap.name == "mssql":
            conn.execute(
                "DECLARE @sql NVARCHAR(MAX) = N'';"
                "SELECT @sql += N'ALTER TABLE '"
                " + QUOTENAME(OBJECT_SCHEMA_NAME(parent_object_id))"
                " + N'.' + QUOTENAME(OBJECT_NAME(parent_object_id))"
                " + N' DROP CONSTRAINT ' + QUOTENAME(name) + N';'"
                " FROM sys.foreign_keys;"
                "IF @sql <> N'' EXEC sp_executesql @sql;"
            )
        sa_conn = _sqlalchemy_connection(conn)
        if sa_conn is not None:
            from sqlalchemy import inspect as sa_inspect

            tables = sa_inspect(sa_conn).get_table_names()
        else:
            engine = conn._sa.engine
            tables = inspect(engine).get_table_names()
        for table in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        if cap.name == "mysql":
            conn.execute("SET FOREIGN_KEY_CHECKS = 1")
        return

    raise RuntimeError(f"Unsupported schema reset for dialect {cap.name!r}")


def supports_create_table_if_not_exists(cap: DialectCapabilities) -> bool:
    """Oracle before 23c lacks ``CREATE TABLE IF NOT EXISTS``."""
    return cap.name != "oracle"


def create_table_sql(table: str, column_ddl: str, cap: DialectCapabilities) -> str:
    if supports_create_table_if_not_exists(cap):
        return f'CREATE TABLE IF NOT EXISTS "{table}" ({column_ddl})'
    return f'CREATE TABLE "{table}" ({column_ddl})'


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
    raw = parsed.path or ""
    if raw.startswith("//"):
        return raw[1:]
    path = raw.lstrip("/")
    if parsed.netloc:
        path = f"/{parsed.netloc}/{path}" if path else f"/{parsed.netloc}"
    elif path and not path.startswith("/"):
        path = str(__import__("pathlib").Path(path).resolve())
    return path or None


def is_serverless_runtime() -> bool:
    """True on Vercel, AWS Lambda, and similar read-only filesystem hosts."""
    import os

    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )


def _sqlite_url_for_path(path: str) -> str:
    from pathlib import Path

    return f"sqlite:///{Path(path).resolve()}"


def resolve_sqlite_dsn_for_runtime(dsn: str) -> str:
    """Use a writable SQLite file on serverless (copy bundled DB to ``/tmp`` once).

    Vercel/Lambda deploy the app bundle read-only. A SQLite file baked in at
    build time (``var/vercel-demo.db``) cannot accept writes; this copies it
    to ``/tmp`` on first use. Prefer ``postgresql://…`` (Supabase) for production.
    """
    normalized = normalize_dsn(dsn)
    if capabilities_from_dsn(normalized).name != "sqlite":
        return normalized
    if not is_serverless_runtime():
        return normalized

    import hashlib
    import os
    import shutil
    from pathlib import Path

    override = (os.environ.get("PYVELM_SQLITE_PATH") or "").strip()
    if override:
        return _sqlite_url_for_path(override)

    source = sqlite_file_path(normalized)
    if source:
        src = Path(source)
        if (
            str(src.resolve()).startswith("/tmp/")
            and src.is_file()
            and os.access(source, os.W_OK)
        ):
            return normalized

    stem = hashlib.sha256((source or normalized).encode()).hexdigest()[:12]
    dest = Path("/tmp") / f"pyvelm-{stem}.db"

    if dest.is_file():
        return _sqlite_url_for_path(str(dest))

    if source and Path(source).is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return _sqlite_url_for_path(str(dest))

    return _sqlite_url_for_path(str(dest))


def delete_sqlite_file(dsn: str) -> None:
    path = sqlite_file_path(dsn)
    if path:
        import os
        from pathlib import Path

        p = Path(path)
        if p.is_file():
            os.remove(p)


def _sqlalchemy_connection(conn) -> SAConnection | None:
    sa = getattr(conn, "_sa", None)
    if isinstance(sa, SAConnection):
        return sa
    return None


def _bind_params(params: tuple, cap: DialectCapabilities) -> tuple:
    """Coerce Python types SQLite's driver rejects (date/time since 3.12)."""
    if cap.name != "sqlite":
        return params
    from datetime import date, datetime, time

    out: list[Any] = []
    for value in params:
        if isinstance(value, datetime):
            out.append(value.isoformat(sep=" "))
        elif isinstance(value, date):
            out.append(value.isoformat())
        elif isinstance(value, time):
            out.append(value.isoformat())
        else:
            out.append(value)
    return tuple(out)


def _conn_capabilities(conn) -> DialectCapabilities:
    cap = getattr(conn, "capabilities", None)
    if cap is not None:
        return cap
    name = getattr(conn, "dialect_name", None)
    if name:
        return dialect_capabilities(name)
    return dialect_capabilities("postgresql")


def timestamp_sql_type(cap: DialectCapabilities) -> str:
    if cap.name == "sqlite":
        return "timestamp"
    if cap.name == "mysql":
        return "DATETIME(6)"
    if cap.name == "mssql":
        return "DATETIMEOFFSET(7)"
    if cap.name == "oracle":
        return "TIMESTAMP WITH TIME ZONE"
    return "timestamptz"


def now_sql(cap: DialectCapabilities) -> str:
    if cap.name == "postgresql":
        return "now()"
    if cap.name == "mssql":
        return "SYSDATETIMEOFFSET()"
    if cap.name == "oracle":
        return "CURRENT_TIMESTAMP"
    return "CURRENT_TIMESTAMP"


_PORTABLE_TYPE_MAP: dict[str, dict[str, str]] = {
    "sqlite": {
        "double precision": "REAL",
        "timestamptz": "timestamp",
        "SERIAL": "INTEGER",
    },
    "mysql": {
        "double precision": "DOUBLE",
        "timestamptz": "DATETIME(6)",
        "timestamp": "DATETIME(6)",
        "boolean": "BOOLEAN",
        "SERIAL": "INTEGER",
    },
    "mssql": {
        "double precision": "FLOAT",
        "timestamptz": "DATETIMEOFFSET(7)",
        "timestamp": "DATETIMEOFFSET(7)",
        "boolean": "BIT",
        "text": "NVARCHAR(MAX)",
        "integer": "INTEGER",
        "SERIAL": "INTEGER",
    },
    "oracle": {
        "double precision": "FLOAT",
        "timestamptz": "TIMESTAMP WITH TIME ZONE",
        "timestamp": "TIMESTAMP",
        "boolean": "NUMBER(1)",
        "text": "CLOB",
        "integer": "INTEGER",
        "SERIAL": "INTEGER",
    },
}


def normalize_sql_type(type_spec: str, cap: DialectCapabilities) -> str:
    """Map Postgres-oriented field types to the active dialect."""
    mapping = _PORTABLE_TYPE_MAP.get(cap.name)
    if not mapping:
        return type_spec
    out = type_spec
    for src, dst in mapping.items():
        out = out.replace(src, dst)
    return out


def normalize_column_ddl(ddl: str, cap: DialectCapabilities) -> str:
    mapping = _PORTABLE_TYPE_MAP.get(cap.name)
    if not mapping:
        return ddl
    out = ddl
    for src, dst in mapping.items():
        out = out.replace(src, dst)
    return out


def string_sql_type(cap: DialectCapabilities, *, primary_key: bool = False) -> str:
    """Portable string column type for Char/Text (MySQL needs VARCHAR for PK/index)."""
    if cap.name == "mysql":
        return "VARCHAR(255)" if primary_key else "TEXT"
    if cap.name == "mssql":
        return "NVARCHAR(255)" if primary_key else "NVARCHAR(MAX)"
    if cap.name == "oracle":
        return "VARCHAR2(255)" if primary_key else "CLOB"
    return "text"


def ir_module_create_sql(cap: DialectCapabilities) -> str:
    ts = timestamp_sql_type(cap)
    default = now_sql(cap)
    name_type = string_sql_type(cap, primary_key=True)
    version_type = string_sql_type(cap)
    return (
        f'CREATE TABLE IF NOT EXISTS "ir_module" ('
        f'"name" {name_type} PRIMARY KEY, '
        f'"version" {version_type} NOT NULL, '
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
    sa_conn = _sqlalchemy_connection(conn)
    if sa_conn is not None:
        from sqlalchemy import inspect as sa_inspect

        # Live connection (not engine) — see column_exists for why.
        return sa_inspect(sa_conn).has_table(table)
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None
