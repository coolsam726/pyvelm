"""DDL via SQLAlchemy Core — no string-built SQL."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Time,
    select,
    text,
)
from sqlalchemy.schema import CreateColumn, CreateTable
from sqlalchemy.sql.expression import func

from .adapter import sqlalchemy_connection
from .capabilities import DialectCapabilities
from .dialects import dialect_capabilities, get_backend
from .ddl import normalize_sql_type

if TYPE_CHECKING:
    from ..fields import Field


def require_sa_connection(conn):
    """Return the SQLAlchemy connection (required for all DDL/DML paths)."""
    sa_conn = sqlalchemy_connection(conn)
    if sa_conn is None:
        raise RuntimeError("SQLAlchemy connection is required.")
    return sa_conn


def _sqlalchemy_dialect(cap: DialectCapabilities):
    if cap.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.dialect()
    if cap.name == "sqlite":
        from sqlalchemy.dialects import sqlite

        return sqlite.dialect()
    if cap.name == "mysql":
        from sqlalchemy.dialects import mysql

        return mysql.dialect()
    if cap.name == "mssql":
        from sqlalchemy.dialects import mssql

        return mssql.dialect()
    if cap.name == "oracle":
        from sqlalchemy.dialects import oracle

        return oracle.dialect()
    raise ValueError(f"Unsupported dialect {cap.name!r}")


def _supports_create_if_not_exists(cap: DialectCapabilities) -> bool:
    return get_backend(cap.name).supports_create_table_if_not_exists()


def sa_type_for_field(field: "Field", cap: DialectCapabilities):
    sql_type = normalize_sql_type(field.sql_type, cap)
    upper = sql_type.upper()
    if cap.name == "mssql":
        if "NVARCHAR" in upper or "VARCHAR" in upper or upper == "TEXT":
            from sqlalchemy.dialects.mssql import NVARCHAR

            import re

            m = re.search(r"\((\d+)\)", sql_type)
            length = int(m.group(1)) if m else 255
            return NVARCHAR(length)
        if "DATETIMEOFFSET" in upper or "TIMESTAMP" in upper or "DATETIME" in upper:
            from sqlalchemy.dialects.mssql import DATETIMEOFFSET

            return DATETIMEOFFSET()
    if upper in ("INTEGER", "INT", "SERIAL", "BIGINT"):
        return Integer()
    if upper in ("TEXT", "CLOB"):
        return Text()
    if "VARCHAR" in upper or "CHAR" in upper:
        import re

        m = re.search(r"\((\d+)\)", sql_type)
        length = int(m.group(1)) if m else 255
        return String(length)
    if "DOUBLE" in upper or upper == "FLOAT":
        return Float()
    if "NUMBER(1)" in upper or upper == "BOOLEAN":
        return Boolean()
    if "TIMESTAMP WITH TIME ZONE" in upper or upper == "TIMESTAMPTZ":
        return DateTime(timezone=True)
    if "TIMESTAMP" in upper:
        return DateTime()
    if upper == "DATE":
        return Date()
    if upper == "TIME":
        return Time()
    return Text()


def primary_key_column(cap: DialectCapabilities) -> Column:
    if cap.name == "sqlite":
        return Column("id", Integer, primary_key=True, autoincrement=True)
    if cap.name in ("mssql", "oracle"):
        from sqlalchemy import Identity

        return Column("id", Integer, Identity(), primary_key=True)
    return Column("id", Integer, primary_key=True, autoincrement=True)


def field_to_column(field: "Field", registry, cap: DialectCapabilities) -> Column:
    """Build a SQLAlchemy column for a stored field."""
    from ..fields import Many2one

    assert field.column is not None
    if isinstance(field, Many2one):
        target = registry[field.comodel_name]
        return Column(
            field.column,
            Integer(),
            ForeignKey(f"{target._table}.id", ondelete=field.ondelete),
            nullable=not field.required,
        )
    return Column(
        field.column,
        sa_type_for_field(field, cap),
        nullable=not field.required,
    )


def model_table_columns(model_cls, registry, cap: DialectCapabilities) -> list[Column]:
    cols = [primary_key_column(cap)]
    for field in model_cls._fields.values():
        if not field.is_stored or field.name == "id" or field.column == "id":
            continue
        cols.append(field_to_column(field, registry, cap))
    return cols


def _metadata_with_tables(*table_names: str) -> MetaData:
    metadata = MetaData()
    for name in table_names:
        if name not in metadata.tables:
            Table(name, metadata, Column("id", Integer, primary_key=True), quote=True)
    return metadata


def m2m_relation_table(
    relation: str,
    col1: str,
    col2: str,
    this_table: str,
    other_table: str,
    cap: DialectCapabilities,
) -> Table:
    metadata = _metadata_with_tables(this_table, other_table)
    return Table(
        relation,
        metadata,
        Column(
            col1,
            Integer(),
            ForeignKey(f"{this_table}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column(
            col2,
            Integer(),
            ForeignKey(f"{other_table}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        PrimaryKeyConstraint(col1, col2),
        quote=True,
    )


def referenced_tables_from_columns(columns: list[Column]) -> set[str]:
    refs: set[str] = set()
    for col in columns:
        for fk in col.foreign_keys:
            target = fk.target_fullname or ""
            if "." in target:
                refs.add(target.split(".", 1)[0])
    return refs


def table_from_columns(
    table_name: str,
    columns: list[Column],
    *,
    referenced_tables: set[str] | None = None,
) -> Table:
    metadata = MetaData()
    for ref in referenced_tables or ():
        if ref == table_name or ref in metadata.tables:
            continue
        Table(ref, metadata, Column("id", Integer, primary_key=True), quote=True)
    return Table(table_name, metadata, *columns, quote=True)


def compile_create_table(table: Table, cap: DialectCapabilities) -> str:
    stmt = CreateTable(table, if_not_exists=_supports_create_if_not_exists(cap))
    return str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))


def execute_create_table(
    conn,
    table: Table | str,
    columns: list[Column] | None = None,
    *,
    cap: DialectCapabilities | None = None,
    referenced_tables: set[str] | None = None,
) -> None:
    """Execute CREATE TABLE for a SQLAlchemy Table or table name + columns."""
    cap = cap or dialect_capabilities(getattr(conn, "dialect_name", "postgresql"))
    sa_conn = require_sa_connection(conn)
    if isinstance(table, Table):
        tbl = table
    else:
        assert columns is not None
        tbl = table_from_columns(table, columns, referenced_tables=referenced_tables)
    sa_conn.execute(CreateTable(tbl, if_not_exists=_supports_create_if_not_exists(cap)))


def compile_add_column(table: str, column: Column, cap: DialectCapabilities) -> str:
    col_sql = str(CreateColumn(column).compile(dialect=_sqlalchemy_dialect(cap)))
    if cap.supports_add_column_if_not_exists:
        return f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {col_sql}'
    add_kw = "ADD" if cap.name in ("mssql", "oracle") else "ADD COLUMN"
    return f'ALTER TABLE "{table}" {add_kw} {col_sql}'


def execute_add_column(
    conn,
    table: str,
    column: Column,
    cap: DialectCapabilities | None = None,
    *,
    if_not_exists: bool = False,
) -> None:
    cap = cap or dialect_capabilities(getattr(conn, "dialect_name", "postgresql"))
    sa_conn = require_sa_connection(conn)
    stmt = compile_add_column(table, column, cap)
    if if_not_exists and not cap.supports_add_column_if_not_exists:
        if_not_exists = False
    if not if_not_exists and " IF NOT EXISTS" in stmt:
        stmt = stmt.replace(" IF NOT EXISTS", "")
    sa_conn.execute(text(stmt))


def execute_sql(
    conn,
    sql: str,
    params: list | tuple | None = None,
) -> None:
    """Execute SQL via SQLAlchemy ``text()`` (requires SA connection)."""
    require_sa_connection(conn)
    conn.execute(sql, params)


def count_null_rows(conn, table: str, column: str) -> int:
    """Count NULL values in a column via SQLAlchemy Core."""
    from sqlalchemy import column as sa_column
    from sqlalchemy import table as sa_table

    sa_conn = require_sa_connection(conn)
    tbl = sa_table(table, sa_column(column))
    stmt = select(func.count()).select_from(tbl).where(sa_column(column).is_(None))
    return int(sa_conn.execute(stmt).scalar_one())
