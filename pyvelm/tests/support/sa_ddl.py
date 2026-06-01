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


def wire_sa_conn(conn, executed, *, dialect_name: str = "postgresql", null_scalar: int = 0):
    """Route SQLAlchemy ``execute`` calls through *executed* as compiled SQL strings."""
    from pyvelm.database.dialects import dialect_capabilities
    from pyvelm.database.sa_ddl import _sqlalchemy_dialect

    cap = dialect_capabilities(dialect_name)

    def _compile(stmt):
        if isinstance(stmt, str):
            return stmt
        return str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))

    def sa_execute(stmt, params=None):
        sql = _compile(stmt)
        executed.append(sql)
        if "count(" in sql.lower() and "null" in sql.lower():
            result = MagicMock()
            result.scalar_one.return_value = null_scalar
            return result
        return conn.execute(sql, params)

    class _SAShim:
        _pyvelm_sa_connection = True

        def execute(self, stmt, params=None):
            return sa_execute(stmt, params)

    conn._sa = _SAShim()
