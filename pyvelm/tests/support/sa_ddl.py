"""Test helpers for SQLAlchemy column DDL compilation."""
from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.schema import CreateColumn

from pyvelm.database.dialects import dialect_capabilities
from pyvelm.database.sa_ddl import _sqlalchemy_dialect


def compiled_column_ddl(field, registry, dialect: str = "postgresql") -> str:
    cap = dialect_capabilities(dialect)
    col = field.sa_column(registry, cap)
    return str(CreateColumn(col).compile(dialect=_sqlalchemy_dialect(cap)))


def wire_sa_conn(
    conn,
    executed,
    *,
    dialect_name: str = "postgresql",
    null_scalar: int = 0,
    base_execute=None,
):
    """Route SQLAlchemy ``execute`` calls through *executed* as compiled SQL strings."""
    from pyvelm.database.dialects import dialect_capabilities
    from pyvelm.database.sa_ddl import _sqlalchemy_dialect

    cap = dialect_capabilities(dialect_name)
    base = base_execute

    def _compile(stmt):
        if isinstance(stmt, str):
            return stmt
        return str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))

    def _append_and_dispatch(sql_str: str, params=None):
        executed.append(sql_str)
        if "count(" in sql_str.lower() and "null" in sql_str.lower():
            result = MagicMock()
            result.scalar_one.return_value = null_scalar
            return result
        if base is not None:
            return base(sql_str, params)
        from unittest.mock import MagicMock as MockType

        execute_fn = getattr(conn, "execute", None)
        if base is None and isinstance(execute_fn, MockType):
            return execute_fn(sql_str, params)
        result = MagicMock()
        result.fetchall.return_value = []
        result.fetchone.return_value = None
        return result

    def sa_execute(stmt, params=None):
        return _append_and_dispatch(_compile(stmt), params)

    class _SAShim:
        _pyvelm_sa_connection = True

        def execute(self, stmt, params=None):
            return sa_execute(stmt, params)

    def conn_execute(sql, params=None):
        sql_str = _compile(sql) if not isinstance(sql, str) else sql
        return _append_and_dispatch(sql_str, params)

    conn._sa = _SAShim()
    if base_execute is not None:
        conn.execute = conn_execute
