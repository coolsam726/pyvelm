"""Connection adapter, pool, and Database handle."""
from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any, Iterator

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection as SAConnection
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from .capabilities import DialectCapabilities
from .dialects import configure_engine, get_backend
from .dsn import capabilities_from_dsn, normalize_dsn
from .sqlite_runtime import resolve_sqlite_dsn_for_runtime


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
        if self.capabilities.name == "oracle" and "%s" in sql:
            # oracledb expects numeric bind markers (:1, :2, ...).
            parts = sql.split("%s")
            out = [parts[0]]
            for idx, part in enumerate(parts[1:], start=1):
                out.append(f":{idx}")
                out.append(part)
            sql = "".join(out)
        elif self.capabilities.placeholder != "%s" and "%s" in sql:
            sql = sql.replace("%s", "?")

        if self.capabilities.name == "mssql":
            # SQL Server rejects boolean literals in WHERE clauses.
            sql = re.sub(r"\bTRUE\b", "1=1", sql)
            sql = re.sub(r"\bFALSE\b", "1=0", sql)
        return sql

    def execute(self, sql: str, params: list | tuple | None = None) -> ExecuteResult:
        sql = self._convert_sql(sql)
        if params is not None:
            bind = get_backend(self.capabilities.name).bind_params(tuple(params))
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
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = QueuePool
            kwargs["pool_size"] = pool_size
            kwargs["max_overflow"] = 0
        else:
            kwargs["pool_size"] = pool_size
            kwargs["max_overflow"] = 0
        engine = create_engine(normalized, **kwargs)
        configure_engine(engine, caps)
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


def sqlalchemy_connection(conn) -> SAConnection | None:
    sa = getattr(conn, "_sa", None)
    if isinstance(sa, SAConnection):
        return sa
    return None


def conn_capabilities(conn) -> DialectCapabilities:
    cap = getattr(conn, "capabilities", None)
    if cap is not None:
        return cap
    name = getattr(conn, "dialect_name", None)
    if name:
        from .dialects import dialect_capabilities

        return dialect_capabilities(name)
    from .dialects import dialect_capabilities

    return dialect_capabilities("postgresql")
