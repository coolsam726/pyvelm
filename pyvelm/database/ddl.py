"""Portable DDL/DML helpers — dispatch to dialect modules."""
from __future__ import annotations

from sqlalchemy import Column, Table, inspect, text

from .adapter import ConnectionAdapter, conn_capabilities, sqlalchemy_connection
from .capabilities import DialectCapabilities, SchemaResetStrategy
from .dialects import get_backend


# Substrings emitted by the various drivers when a CREATE collides with an
# object that already exists. Keep this list in one place so every CREATE path
# (model setup, autogen schema diff, …) treats the collision identically.
_DUPLICATE_OBJECT_MARKERS = (
    "already exists",  # postgres / mysql / sqlite
    "already an object named",  # mssql
    "name is already used by an existing object",  # oracle ORA-00955
    "ora-00955",  # oracle (numeric form, in case the message is localized)
)


def is_duplicate_object_error(exc: BaseException) -> bool:
    """True when *exc* means "CREATE failed because the object already exists".

    Backends without ``CREATE TABLE IF NOT EXISTS`` (Oracle, SQL Server) raise
    instead of no-oping, and their inspectors can briefly disagree with the live
    schema. Callers use this to treat a duplicate as success and continue.
    """
    msg = str(getattr(exc, "orig", exc)).lower()
    return any(marker in msg for marker in _DUPLICATE_OBJECT_MARKERS)


def serial_primary_key(cap: DialectCapabilities) -> str:
    return get_backend(cap.name).serial_primary_key()


def returning_id_clause(cap: DialectCapabilities) -> str:
    # Oracle RETURNING requires an INTO target/bind variable. Our generic
    # exec_driver_sql path appends only `RETURNING "id"` so it fails with
    # ORA-00925. Fall back to dialect fetch_lastrowid() for Oracle.
    if cap.name == "oracle":
        return ""
    if cap.name == "sqlite" and cap.supports_returning:
        return ' RETURNING "id"'
    if cap.supports_returning:
        return ' RETURNING "id"'
    return ""


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    cap = conn_capabilities(conn)
    return get_backend(cap.name).fetch_lastrowid(conn, table)


def append_search_pagination(
    sql: str,
    *,
    base_table_sql: str,
    limit: int | None,
    offset: int,
    order: str | None,
    cap: DialectCapabilities,
) -> str:
    if limit is None and not offset:
        return sql
    backend = get_backend(cap.name)
    if cap.name in ("postgresql", "mysql", "sqlite"):
        return backend.append_search_pagination(
            sql,
            base_table_sql=base_table_sql,
            limit=limit,
            offset=offset,
            order=order,
        )
    return backend.append_search_pagination(
        sql,
        base_table_sql=base_table_sql,
        limit=limit,
        offset=offset,
        order=order,
    )


def ilike_sql(column_sql: str, cap: DialectCapabilities) -> str:
    if cap.supports_ilike:
        return f"{column_sql} ILIKE %s"
    return f"LOWER({column_sql}) LIKE LOWER(%s)"


def add_column_sql(
    table: str, column: str, sql_type: str, cap: DialectCapabilities
) -> str:
    """Portable ``ALTER TABLE … ADD …`` (SQL Server/Oracle omit ``COLUMN``)."""
    add_kw = "ADD" if cap.name in ("mssql", "oracle") else "ADD COLUMN"
    return f'ALTER TABLE "{table}" {add_kw} "{column}" {sql_type}'


def add_column_if_not_exists_sql(
    table: str, column: str, sql_type: str, cap: DialectCapabilities
) -> str | None:
    if cap.supports_add_column_if_not_exists:
        return (
            f'ALTER TABLE "{table}" '
            f'ADD COLUMN IF NOT EXISTS "{column}" {sql_type}'
        )
    return None


def add_column_if_missing(
    conn,
    table: str,
    column: str,
    sql_type: str,
    cap: DialectCapabilities | None = None,
    *,
    registry=None,
    field=None,
) -> bool:
    from .introspection import column_exists
    from .sa_ddl import execute_add_column, field_to_column
    from sqlalchemy import Column

    cap = cap or conn_capabilities(conn)
    if column_exists(conn, table, column, cap):
        return False
    if field is not None and registry is not None:
        col = field_to_column(field, registry, cap)
    else:
        from .sa_ddl import sa_type_for_field
        from ..fields import Field

        stub = Field(column=column)
        stub.sql_type = sql_type
        col = Column(column, sa_type_for_field(stub, cap), nullable=True)
    try:
        execute_add_column(
            conn,
            table,
            col,
            cap,
            if_not_exists=cap.supports_add_column_if_not_exists,
        )
        return True
    except Exception as exc:
        orig = getattr(exc, "orig", exc)
        msg = str(orig).lower()
        if get_backend(cap.name).is_duplicate_column_error(msg):
            return False
        raise


def reset_schema(conn: ConnectionAdapter, cap: DialectCapabilities) -> None:
    """Backend-specific schema wipe for migrate:reset / migrate:fresh."""
    from .sa_ddl import execute_sql

    if cap.schema_reset == SchemaResetStrategy.DROP_SCHEMA:
        execute_sql(conn, "DROP SCHEMA IF EXISTS public CASCADE")
        execute_sql(conn, "CREATE SCHEMA public")
        execute_sql(conn, "GRANT ALL ON SCHEMA public TO public")
        return

    if cap.schema_reset == SchemaResetStrategy.DROP_ALL_TABLES:
        backend = get_backend(cap.name)
        # A backend may provide an authoritative wipe (e.g. Oracle, where the
        # SQLAlchemy inspector hides recyclebin/phantom objects and a plain
        # DROP leaves state behind that resurfaces as ORA-00955). Prefer it.
        reset_all_tables = getattr(backend, "reset_all_tables", None)
        if reset_all_tables is not None:
            reset_all_tables(conn)
            return
        backend.before_reset_all_tables(conn)
        sa_conn = sqlalchemy_connection(conn)
        if sa_conn is not None:
            from sqlalchemy import inspect as sa_inspect

            tables = sa_inspect(sa_conn).get_table_names()
        else:
            tables = inspect(conn._sa.engine).get_table_names()
        for table in tables:
            if cap.name == "oracle":
                execute_sql(conn, f'DROP TABLE "{table}"')
            else:
                execute_sql(conn, f'DROP TABLE IF EXISTS "{table}"')
        backend.after_reset_all_tables(conn)
        return

    raise RuntimeError(f"Unsupported schema reset for dialect {cap.name!r}")


def supports_create_table_if_not_exists(cap: DialectCapabilities) -> bool:
    return get_backend(cap.name).supports_create_table_if_not_exists()


def create_table_sql(
    table: str, columns: list, cap: DialectCapabilities
) -> str:
    from .sa_ddl import (
        compile_create_table,
        referenced_tables_from_columns,
        table_from_columns,
    )

    tbl = table_from_columns(
        table,
        columns,
        referenced_tables=referenced_tables_from_columns(columns),
        cap=cap,
    )
    return compile_create_table(tbl, cap)


def migration_supported(
    env_conn: ConnectionAdapter, supported_backends: tuple[str, ...] | None
) -> bool:
    if not supported_backends:
        supported_backends = ("postgresql",)
    return env_conn.dialect_name in supported_backends


def timestamp_sql_type(cap: DialectCapabilities) -> str:
    return get_backend(cap.name).timestamp_sql_type()


def now_sql(cap: DialectCapabilities) -> str:
    return get_backend(cap.name).now_sql()


def normalize_sql_type(type_spec: str, cap: DialectCapabilities) -> str:
    mapping = get_backend(cap.name).PORTABLE_TYPE_MAP
    if not mapping:
        return type_spec
    out = type_spec
    for src, dst in mapping.items():
        out = out.replace(src, dst)
    return out


def normalize_column_ddl(ddl: str, cap: DialectCapabilities) -> str:
    mapping = get_backend(cap.name).PORTABLE_TYPE_MAP
    if not mapping:
        return ddl
    out = ddl
    for src, dst in mapping.items():
        out = out.replace(src, dst)
    return out


def string_sql_type(cap: DialectCapabilities, *, primary_key: bool = False) -> str:
    return get_backend(cap.name).string_sql_type(primary_key=primary_key)


def ir_module_table(cap: DialectCapabilities) -> Table:
    from .sa_ddl import _column_quote_kw, sa_type_for_field, table_from_columns
    from ..fields import Field

    quote_kw = _column_quote_kw(cap)
    name_f = Field(column="name", required=True)
    name_f.sql_type = string_sql_type(cap, primary_key=True)
    version_f = Field(column="version", required=True)
    version_f.sql_type = string_sql_type(cap)
    installed_f = Field(column="installed_at", required=True)
    installed_f.sql_type = timestamp_sql_type(cap)
    cols = [
        Column(
            "name",
            sa_type_for_field(name_f, cap),
            primary_key=True,
            nullable=False,
            **quote_kw,
        ),
        Column(
            "version",
            sa_type_for_field(version_f, cap),
            nullable=False,
            **quote_kw,
        ),
    ]
    installed_col = Column(
        "installed_at",
        sa_type_for_field(installed_f, cap),
        nullable=False,
        **quote_kw,
    )
    if cap.name in ("postgresql", "sqlite"):
        installed_col.server_default = text(now_sql(cap))
    cols.append(installed_col)
    return table_from_columns("ir_module", cols, cap=cap)


def ir_module_create_sql(cap: DialectCapabilities) -> str:
    from .sa_ddl import compile_create_table

    return compile_create_table(ir_module_table(cap), cap)
