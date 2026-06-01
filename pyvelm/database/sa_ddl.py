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


def uses_inline_foreign_keys(cap: DialectCapabilities) -> bool:
    """Dialects that embed FOREIGN KEY in CREATE TABLE (not ALTER after)."""
    return cap.name in ("sqlite", "mysql", "mssql", "oracle")


def columns_use_quoted_identifiers(cap: DialectCapabilities) -> bool:
    """Dialects where DDL must quote columns to match runtime ``"col"`` SQL."""
    return cap.name in ("oracle", "mssql")


def ddl_quote_identifier(name: str, cap: DialectCapabilities) -> str:
    """Quote a table/column name for hand-built DDL strings."""
    if cap.name == "mssql":
        escaped = name.replace("]", "]]")
        return f"[{escaped}]"
    return f'"{name}"'


def _column_quote_kw(cap: DialectCapabilities) -> dict[str, bool]:
    return {"quote": True} if columns_use_quoted_identifiers(cap) else {}


def effective_fk_ondelete(
    ondelete: str,
    *,
    local_table: str,
    ref_table: str,
    cap: DialectCapabilities,
) -> str:
    """Dialect-adjusted ON DELETE for inline / ALTER foreign keys.

    SQL Server rejects self-referential ``ON DELETE CASCADE`` (error 1785).
    Use ``NO ACTION`` at the database and cascade in ``BaseModel.unlink``.
    """
    action = (ondelete or "CASCADE").upper().replace("_", " ")
    if cap.name == "mssql" and local_table == ref_table and action == "CASCADE":
        return "NO ACTION"
    return action


def model_cls_for_table(registry, table_name: str):
    """Return the model class for a physical table name, if registered."""
    if registry is None:
        return None
    for cls in registry:
        if cls._table == table_name:
            return cls
    return None


def _core_column_type(
    col_name: str,
    cap: DialectCapabilities,
    registry,
    model_cls,
):
    if col_name == "id":
        return Integer()
    if model_cls is not None and registry is not None:
        for field in model_cls._fields.values():
            if field.is_stored and field.column == col_name:
                return sa_type_for_field(field, cap)
    if col_name.endswith("_id"):
        return Integer()
    return Text()


def core_table(
    table_name: str,
    cap: DialectCapabilities,
    *column_names: str,
    registry=None,
    model_cls=None,
) -> Table:
    """MetaData-bound table for SQLAlchemy Core DML (matches DDL quoting).

    ``TableClause`` (``table("t", column("c"))``) emits unquoted names on
    Oracle/MSSQL, which do not match quoted CREATE TABLE identifiers.

    Pass *registry* / *model_cls* (or rely on table lookup) so INSERT/UPDATE
    bind parameters use real column types, not ``Text()`` for every column.
    """
    from sqlalchemy import Column, MetaData, Table

    if model_cls is None and registry is not None:
        model_cls = model_cls_for_table(registry, table_name)
    names = tuple(dict.fromkeys(column_names or ("id",)))
    quote_kw = _column_quote_kw(cap)
    metadata = MetaData()
    cols = [
        Column(
            name,
            _core_column_type(name, cap, registry, model_cls),
            **quote_kw,
        )
        for name in names
    ]
    return Table(table_name, metadata, *cols, quote=True)


def sa_type_for_field(field: "Field", cap: DialectCapabilities):
    sql_type = normalize_sql_type(field.sql_type, cap)
    upper = sql_type.upper()
    if cap.name == "mssql":
        if "NVARCHAR" in upper or "VARCHAR" in upper or upper == "TEXT":
            from sqlalchemy.dialects.mssql import NVARCHAR

            import re

            if "MAX" in upper:
                return NVARCHAR(None)
            m = re.search(r"\((\d+)\)", sql_type)
            if m:
                return NVARCHAR(int(m.group(1)))
            return NVARCHAR(None)
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
    quote_kw = _column_quote_kw(cap)
    if cap.name == "sqlite":
        return Column(
            "id", Integer, primary_key=True, autoincrement=True, **quote_kw
        )
    if cap.name in ("mssql", "oracle"):
        from sqlalchemy import Identity

        return Column("id", Integer, Identity(), primary_key=True, **quote_kw)
    return Column("id", Integer, primary_key=True, autoincrement=True, **quote_kw)


def field_to_column(
    field: "Field",
    registry,
    cap: DialectCapabilities,
    *,
    local_table: str | None = None,
) -> Column:
    """Build a SQLAlchemy column for a stored field."""
    from ..fields import Many2one

    assert field.column is not None
    quote_kw = _column_quote_kw(cap)
    if isinstance(field, Many2one):
        if not uses_inline_foreign_keys(cap):
            return Column(
                field.column,
                Integer(),
                nullable=not field.required,
                **quote_kw,
            )
        target = registry[field.comodel_name]
        ondelete = field.ondelete
        if local_table is not None:
            ondelete = effective_fk_ondelete(
                ondelete,
                local_table=local_table,
                ref_table=target._table,
                cap=cap,
            )
        return Column(
            field.column,
            Integer(),
            ForeignKey(f"{target._table}.id", ondelete=ondelete),
            nullable=not field.required,
            **quote_kw,
        )
    return Column(
        field.column,
        sa_type_for_field(field, cap),
        nullable=not field.required,
        **quote_kw,
    )


def model_table_columns(model_cls, registry, cap: DialectCapabilities) -> list[Column]:
    cols = [primary_key_column(cap)]
    for field in model_cls._fields.values():
        if not field.is_stored or field.name == "id" or field.column == "id":
            continue
        cols.append(field_to_column(field, registry, cap, local_table=model_cls._table))
    return cols


def _metadata_with_tables(*table_names: str, cap: DialectCapabilities | None = None) -> MetaData:
    metadata = MetaData()
    cap = cap or dialect_capabilities("postgresql")
    quote_kw = _column_quote_kw(cap)
    for name in table_names:
        if name not in metadata.tables:
            Table(
                name,
                metadata,
                Column("id", Integer, primary_key=True, **quote_kw),
                quote=True,
            )
    return metadata


def m2m_relation_table(
    relation: str,
    col1: str,
    col2: str,
    this_table: str,
    other_table: str,
    cap: DialectCapabilities,
) -> Table:
    quote_kw = _column_quote_kw(cap)
    this_fk = f"{this_table}.id"
    other_fk = f"{other_table}.id"
    metadata = _metadata_with_tables(this_table, other_table, cap=cap)
    return Table(
        relation,
        metadata,
        Column(
            col1,
            Integer(),
            ForeignKey(this_fk, ondelete="CASCADE"),
            nullable=False,
            **quote_kw,
        ),
        Column(
            col2,
            Integer(),
            ForeignKey(other_fk, ondelete="CASCADE"),
            nullable=False,
            **quote_kw,
        ),
        PrimaryKeyConstraint(col1, col2),
        quote=True,
    )


def _fk_target_table_name(target: str) -> str:
    return target.split(".", 1)[0].strip('"')


def referenced_tables_from_columns(columns: list[Column]) -> set[str]:
    refs: set[str] = set()
    for col in columns:
        for fk in col.foreign_keys:
            target = fk.target_fullname or ""
            if "." in target:
                refs.add(_fk_target_table_name(target))
    return refs


def table_from_columns(
    table_name: str,
    columns: list[Column],
    *,
    referenced_tables: set[str] | None = None,
    cap: DialectCapabilities | None = None,
) -> Table:
    cap = cap or dialect_capabilities("postgresql")
    metadata = MetaData()
    quote_kw = _column_quote_kw(cap)
    for ref in referenced_tables or ():
        if ref == table_name or ref in metadata.tables:
            continue
        Table(
            ref,
            metadata,
            Column("id", Integer, primary_key=True, **quote_kw),
            quote=True,
        )
    return Table(table_name, metadata, *columns, quote=True)


def compile_create_table(table: Table, cap: DialectCapabilities) -> str:
    stmt = CreateTable(table, if_not_exists=_supports_create_if_not_exists(cap))
    return str(stmt.compile(dialect=_sqlalchemy_dialect(cap)))


def _execute_create_table_stmt(
    conn,
    sa_conn,
    table: Table,
    *,
    cap: DialectCapabilities,
    if_not_exists: bool,
) -> None:
    """Run ``CREATE TABLE`` when the table is missing; ignore duplicate-object races."""
    from .ddl import is_duplicate_object_error
    from .introspection import clear_reflection_cache, table_exists

    if table_exists(conn, table.name, cap):
        return
    try:
        sa_conn.execute(CreateTable(table, if_not_exists=if_not_exists))
    except Exception as exc:
        if is_duplicate_object_error(exc):
            clear_reflection_cache(conn)
            return
        raise


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
        tbl = table_from_columns(
            table, columns, referenced_tables=referenced_tables, cap=cap
        )
    if_not_exists = _supports_create_if_not_exists(cap)
    # Stub FK targets in ``tbl.metadata`` must exist before inline FOREIGN KEY
    # clauses are applied (MySQL/MSSQL/Oracle; Postgres uses ALTER for FKs).
    for dep_name, dep_tbl in sorted(tbl.metadata.tables.items()):
        if dep_name != tbl.name:
            _execute_create_table_stmt(
                conn, sa_conn, dep_tbl, cap=cap, if_not_exists=if_not_exists
            )
    _execute_create_table_stmt(
        conn, sa_conn, tbl, cap=cap, if_not_exists=if_not_exists
    )


def sort_models_for_table_setup(models: list[type], registry) -> list[type]:
    """Order models so Many2one targets are created before dependents.

    Pulls FK target models from the live registry (cross-module ``_inherit``).
    """
    from ..fields import Many2one

    by_name: dict[str, type] = {}
    model_list: list[type] = []

    def include(cls: type) -> None:
        if cls._name in by_name:
            return
        by_name[cls._name] = cls
        model_list.append(cls)

    for cls in models:
        include(cls)

    expanded = True
    while expanded:
        expanded = False
        for cls in list(model_list):
            for field in cls._fields.values():
                if not isinstance(field, Many2one):
                    continue
                if field.related or not field.is_stored:
                    continue
                comodel = field.comodel_name
                if comodel not in registry or comodel in by_name:
                    continue
                include(registry[comodel])
                expanded = True

    deps: dict[str, set[str]] = {name: set() for name in by_name}
    for cls in model_list:
        for field in cls._fields.values():
            if not isinstance(field, Many2one):
                continue
            if field.related or not field.is_stored:
                continue
            if field.comodel_name not in by_name:
                continue
            if field.comodel_name != cls._name:
                deps[cls._name].add(field.comodel_name)

    ordered: list[type] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        for dep in deps.get(name, ()):
            visit(dep)
        seen.add(name)
        ordered.append(by_name[name])

    for cls in model_list:
        visit(cls._name)
    return ordered


def table_bound_column(table_name: str, column: Column) -> Column:
    """Return *column* bound to *table_name* (required by MSSQL DDL compilation)."""
    if column.table is not None:
        return column
    tbl = Table(table_name, MetaData(), column, quote=True)
    return tbl.c[column.key]


def compile_add_column(table: str, column: Column, cap: DialectCapabilities) -> str:
    bound = table_bound_column(table, column)
    col_sql = str(CreateColumn(bound).compile(dialect=_sqlalchemy_dialect(cap)))
    tbl_sql = ddl_quote_identifier(table, cap)
    if cap.supports_add_column_if_not_exists:
        return f"ALTER TABLE {tbl_sql} ADD COLUMN IF NOT EXISTS {col_sql}"
    add_kw = "ADD" if cap.name in ("mssql", "oracle") else "ADD COLUMN"
    return f"ALTER TABLE {tbl_sql} {add_kw} {col_sql}"


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
):
    """Execute SQL via SQLAlchemy ``text()`` (requires SA connection)."""
    require_sa_connection(conn)
    return conn.execute(sql, params)


def count_null_rows(conn, table: str, column: str) -> int:
    """Count NULL values in a column via SQLAlchemy Core."""
    from sqlalchemy import column as sa_column
    from sqlalchemy import table as sa_table

    sa_conn = require_sa_connection(conn)
    tbl = sa_table(table, sa_column(column))
    stmt = select(func.count()).select_from(tbl).where(sa_column(column).is_(None))
    return int(sa_conn.execute(stmt).scalar_one())
