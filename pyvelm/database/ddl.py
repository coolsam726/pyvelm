"""Portable DDL/DML helpers — dispatch to dialect modules."""
from __future__ import annotations

from sqlalchemy import inspect

from .adapter import ConnectionAdapter, conn_capabilities, sqlalchemy_connection
from .capabilities import DialectCapabilities, SchemaResetStrategy
from .dialects import get_backend


def serial_primary_key(cap: DialectCapabilities) -> str:
    return get_backend(cap.name).serial_primary_key()


def returning_id_clause(cap: DialectCapabilities) -> str:
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
) -> bool:
    from .introspection import column_exists

    cap = cap or conn_capabilities(conn)
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
        if get_backend(cap.name).is_duplicate_column_error(msg):
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
        backend = get_backend(cap.name)
        backend.before_reset_all_tables(conn)
        sa_conn = sqlalchemy_connection(conn)
        if sa_conn is not None:
            from sqlalchemy import inspect as sa_inspect

            tables = sa_inspect(sa_conn).get_table_names()
        else:
            tables = inspect(conn._sa.engine).get_table_names()
        for table in tables:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        backend.after_reset_all_tables(conn)
        return

    raise RuntimeError(f"Unsupported schema reset for dialect {cap.name!r}")


def supports_create_table_if_not_exists(cap: DialectCapabilities) -> bool:
    return get_backend(cap.name).supports_create_table_if_not_exists()


def create_table_sql(table: str, column_ddl: str, cap: DialectCapabilities) -> str:
    if supports_create_table_if_not_exists(cap):
        return f'CREATE TABLE IF NOT EXISTS "{table}" ({column_ddl})'
    return f'CREATE TABLE "{table}" ({column_ddl})'


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


def ir_module_create_sql(cap: DialectCapabilities) -> str:
    ts = timestamp_sql_type(cap)
    default = now_sql(cap)
    name_type = string_sql_type(cap, primary_key=True)
    version_type = string_sql_type(cap)
    column_ddl = (
        f'"name" {name_type} PRIMARY KEY, '
        f'"version" {version_type} NOT NULL, '
        f'"installed_at" {ts} NOT NULL DEFAULT {default}'
    )
    return create_table_sql("ir_module", column_ddl, cap)
