"""DDL via SQLAlchemy Core (CreateTable, AddColumn)."""
from __future__ import annotations

import re
from typing import Any

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
)
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

from .adapter import sqlalchemy_connection
from .capabilities import DialectCapabilities
from .dialects import dialect_capabilities, get_backend

_FK_RE = re.compile(
    r'REFERENCES\s+"([^"]+)"\("([^"]+)"\)'
    r"(?:\s+ON\s+DELETE\s+(CASCADE|SET NULL|RESTRICT))?",
    re.IGNORECASE,
)


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


def _split_column_ddls(columns_ddl: str) -> list[str]:
    """Split a CREATE TABLE column list on commas between quoted columns."""
    pk_clause = ""
    body = columns_ddl.strip()
    pk_match = re.search(
        r",\s*(PRIMARY KEY\s*\([^)]+\))\s*$", body, re.IGNORECASE
    )
    if pk_match:
        pk_clause = pk_match.group(1)
        body = body[: pk_match.start()].strip()
    parts = [part.strip() for part in re.split(r",\s*(?=\")", body) if part.strip()]
    if pk_clause:
        parts.append(pk_clause)
    return parts


def _parse_column_ddl(
    ddl: str,
) -> tuple[str, str, bool, bool, str | None]:
    ddl = ddl.strip()
    not_null = False
    primary_key = False
    default_sql: str | None = None
    upper = ddl.upper()
    if upper.endswith(" NOT NULL"):
        not_null = True
        ddl = ddl[: upper.rfind(" NOT NULL")].strip()
        upper = ddl.upper()
    match = re.match(r'^"([^"]+)"\s+(.+)$', ddl, re.DOTALL)
    if not match:
        raise ValueError(f"Invalid column DDL: {ddl!r}")
    name, type_rest = match.group(1), match.group(2).strip()
    if type_rest.upper().endswith(" PRIMARY KEY"):
        primary_key = True
        type_rest = type_rest[: -len(" PRIMARY KEY")].strip()
    default_match = re.search(r"\s+DEFAULT\s+(.+)$", type_rest, re.IGNORECASE)
    if default_match:
        default_sql = default_match.group(1).strip()
        type_rest = type_rest[: default_match.start()].strip()
    return name, type_rest, not_null, primary_key, default_sql


def _is_primary_key_ddl(ddl: str) -> bool:
    return '"id"' in ddl.lower() and "PRIMARY KEY" in ddl.upper()


def _sa_type_from_spec(type_spec: str, cap: DialectCapabilities):
    spec = type_spec.strip()
    upper = spec.upper()
    if cap.name == "mssql":
        if "NVARCHAR" in upper or "VARCHAR" in upper or upper == "TEXT":
            from sqlalchemy.dialects.mssql import NVARCHAR

            m = re.search(r"\((\d+)\)", spec)
            length = int(m.group(1)) if m else 255
            return NVARCHAR(length)
        if "DATETIMEOFFSET" in upper or "TIMESTAMP" in upper or "DATETIME" in upper:
            from sqlalchemy.dialects.mssql import DATETIMEOFFSET

            return DATETIMEOFFSET()
    if upper in ("INTEGER", "INT", "SERIAL", "BIGINT"):
        return Integer()
    if upper in ("TEXT", "CLOB"):
        return Text()
    if "VARCHAR" in upper or "NVARCHAR" in upper or "CHAR" in upper:
        m = re.search(r"\((\d+)\)", spec)
        length = int(m.group(1)) if m else 255
        return String(length)
    if "DOUBLE" in upper or upper == "FLOAT":
        return Float()
    if "NUMBER(1)" in upper or upper == "BOOLEAN":
        return Boolean()
    if "TIMESTAMP WITH TIME ZONE" in upper or upper == "TIMESTAMPTZ":
        return DateTime(timezone=True)
    if "TIMESTAMP" in upper or "DATETIMEOFFSET" in upper:
        return DateTime()
    if upper == "DATE":
        return Date()
    if upper == "TIME":
        return Time()
    if upper.startswith("JSON"):
        from sqlalchemy.dialects.postgresql import JSONB

        return JSONB()
    return Text()


def primary_key_column(cap: DialectCapabilities) -> Column:
    if cap.name == "sqlite":
        return Column("id", Integer, primary_key=True, autoincrement=True)
    if cap.name in ("mssql", "oracle"):
        from sqlalchemy import Identity

        return Column("id", Integer, Identity(), primary_key=True)
    return Column("id", Integer, primary_key=True, autoincrement=True)


def column_from_ddl(ddl: str, cap: DialectCapabilities) -> Column:
    """Build a SQLAlchemy column from a normalized ``column_ddl()`` string."""
    if _is_primary_key_ddl(ddl):
        return primary_key_column(cap)
    name, type_rest, not_null, primary_key, default_sql = _parse_column_ddl(ddl)
    fk_match = _FK_RE.search(type_rest)
    ondelete = None
    if fk_match:
        type_spec = type_rest[: fk_match.start()].strip()
        ref_table, ref_col = fk_match.group(1), fk_match.group(2)
        ondelete = (fk_match.group(3) or "").upper() or None
    else:
        type_spec = type_rest
        ref_table = ref_col = None
    col_type = _sa_type_from_spec(type_spec, cap)
    col_kw: dict[str, Any] = {
        "nullable": not (not_null or primary_key),
        "primary_key": primary_key,
    }
    if default_sql is not None:
        col_kw["server_default"] = text(default_sql)
    if ref_table:
        fk_kw: dict[str, Any] = {}
        if ondelete:
            fk_kw["ondelete"] = ondelete
        return Column(
            name,
            Integer(),
            ForeignKey(f"{ref_table}.{ref_col}", **fk_kw),
            **col_kw,
        )
    return Column(name, col_type, **col_kw)


def _create_table_sql_legacy(
    table: str, columns_ddl: str | list[str], cap: DialectCapabilities
) -> str:
    if isinstance(columns_ddl, list):
        body = ", ".join(columns_ddl)
    else:
        body = columns_ddl
    if _supports_create_if_not_exists(cap):
        return f'CREATE TABLE IF NOT EXISTS "{table}" ({body})'
    return f'CREATE TABLE "{table}" ({body})'


def _column_spec_list(columns_ddl: str | list[str]) -> list[str]:
    if isinstance(columns_ddl, list):
        return list(columns_ddl)
    return _split_column_ddls(columns_ddl)


def _needs_legacy_ddl(specs: list[str]) -> bool:
    return any("REFERENCES" in spec.upper() for spec in specs)


def _table_from_column_ddls(
    table: str, columns_ddl: str | list[str], cap: DialectCapabilities
) -> Table:
    metadata = MetaData()
    if isinstance(columns_ddl, str):
        specs = _split_column_ddls(columns_ddl)
    else:
        specs = list(columns_ddl)
    columns: list[Column] = []
    pk_constraint: PrimaryKeyConstraint | None = None
    for spec in specs:
        if spec.upper().startswith("PRIMARY KEY"):
            match = re.search(r"PRIMARY KEY\s*\(([^)]+)\)", spec, re.IGNORECASE)
            if not match:
                raise ValueError(f"Invalid PRIMARY KEY clause: {spec!r}")
            pk_cols = [c.strip().strip('"') for c in match.group(1).split(",")]
            pk_constraint = PrimaryKeyConstraint(*pk_cols)
            continue
        columns.append(column_from_ddl(spec, cap))
    if pk_constraint is not None:
        return Table(table, metadata, *columns, pk_constraint, quote=True)
    return Table(table, metadata, *columns, quote=True)


def compile_create_table(
    table: str, columns_ddl: str | list[str], cap: DialectCapabilities
) -> str:
    """Compile CREATE TABLE DDL via SQLAlchemy."""
    specs = _column_spec_list(columns_ddl)
    if _needs_legacy_ddl(specs):
        return _create_table_sql_legacy(table, specs, cap)
    tbl = _table_from_column_ddls(table, specs, cap)
    stmt = CreateTable(tbl, if_not_exists=_supports_create_if_not_exists(cap))
    return str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))


def execute_create_table(
    conn,
    table: str,
    columns_ddl: str | list[str],
    cap: DialectCapabilities | None = None,
) -> None:
    """Execute CREATE TABLE via SQLAlchemy Core (requires SA connection)."""
    cap = cap or dialect_capabilities(getattr(conn, "dialect_name", "postgresql"))
    specs = _column_spec_list(columns_ddl)
    if _needs_legacy_ddl(specs):
        ddl = _create_table_sql_legacy(table, specs, cap)
        sa_conn = sqlalchemy_connection(conn)
        if sa_conn is not None:
            sa_conn.execute(text(ddl))
        else:
            conn.execute(ddl)
        return
    sa_conn = sqlalchemy_connection(conn)
    if sa_conn is None:
        conn.execute(_create_table_sql_legacy(table, specs, cap))
        return
    tbl = _table_from_column_ddls(table, specs, cap)
    stmt = CreateTable(tbl, if_not_exists=_supports_create_if_not_exists(cap))
    sa_conn.execute(stmt)


def execute_add_column(
    conn,
    table: str,
    column_ddl: str,
    cap: DialectCapabilities | None = None,
    *,
    if_not_exists: bool = False,
) -> None:
    """Execute ALTER TABLE ADD COLUMN via SQLAlchemy ``text()``."""
    from .ddl import add_column_if_not_exists_sql, add_column_sql

    cap = cap or dialect_capabilities(getattr(conn, "dialect_name", "postgresql"))
    sa_conn = sqlalchemy_connection(conn)
    if sa_conn is None:
        raise RuntimeError("SQLAlchemy connection is required for DDL.")
    name, type_spec, _not_null, _pk, _default = _parse_column_ddl(column_ddl)
    stmt = (
        add_column_if_not_exists_sql(table, name, type_spec, cap)
        if if_not_exists
        else add_column_sql(table, name, type_spec, cap)
    )
    if stmt is None:
        stmt = add_column_sql(table, name, type_spec, cap)
    sa_conn.execute(text(stmt))
