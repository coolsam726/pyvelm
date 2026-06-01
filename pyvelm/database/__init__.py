"""SQLAlchemy-backed database engine, pool, and psycopg-compatible connection adapter.

v1.x portability layer — see docs/multi-database.md and docs/adr/001-sqlalchemy-core.md.
"""
from __future__ import annotations

from .adapter import (
    ConnectionAdapter,
    Database,
    ExecuteResult,
    PoolFacade,
    conn_capabilities,
    create_database_from_dsn,
    sqlalchemy_connection,
)
from .capabilities import DialectCapabilities, SchemaResetStrategy, dialect_base_name
from .ddl import (
    add_column_if_missing,
    add_column_if_not_exists_sql,
    append_search_pagination,
    create_table_sql,
    fetch_lastrowid,
    ilike_sql,
    ir_module_create_sql,
    ir_module_table,
    is_duplicate_object_error,
    migration_supported,
    normalize_column_ddl,
    normalize_sql_type,
    now_sql,
    reset_schema,
    returning_id_clause,
    serial_primary_key,
    string_sql_type,
    supports_create_table_if_not_exists,
    timestamp_sql_type,
)
from .dialects import configure_engine, dialect_capabilities, get_backend
from .dsn import capabilities_from_dsn, normalize_dsn, to_psycopg_dsn
from .env import (
    TEST_DSN_ENV,
    app_dsn_from_env,
    dsn_display,
    is_serverless_runtime,
    is_supabase_direct_host,
    is_transaction_pooler_dsn,
    load_testing_env,
    nuke_dsn_from_env,
    require_dsn_from_env,
    require_test_dsn_from_env,
    test_dsn_from_env,
    uses_serverless_schema_wipe,
    warn_if_poor_nuke_dsn,
)
from .introspection import column_exists, table_exists
from .sa_ddl import compile_create_table, execute_create_table, execute_sql
from .postgres_admin import (
    prepare_postgres_schema_drop,
    release_postgres_schema_drop_lock,
    terminate_other_backends,
)
from .sqlite_runtime import delete_sqlite_file, resolve_sqlite_dsn_for_runtime, sqlite_file_path

# Backward-compatible private aliases used across pyvelm.
_conn_capabilities = conn_capabilities
_sqlalchemy_connection = sqlalchemy_connection
_configure_engine = configure_engine


def _bind_params(params: tuple, cap: DialectCapabilities) -> tuple:
    return get_backend(cap.name).bind_params(params)


__all__ = [
    "TEST_DSN_ENV",
    "ConnectionAdapter",
    "Database",
    "DialectCapabilities",
    "ExecuteResult",
    "PoolFacade",
    "SchemaResetStrategy",
    "add_column_if_missing",
    "add_column_if_not_exists_sql",
    "append_search_pagination",
    "app_dsn_from_env",
    "capabilities_from_dsn",
    "column_exists",
    "compile_create_table",
    "configure_engine",
    "conn_capabilities",
    "create_database_from_dsn",
    "create_table_sql",
    "execute_create_table",
    "execute_sql",
    "delete_sqlite_file",
    "dialect_base_name",
    "dialect_capabilities",
    "dsn_display",
    "fetch_lastrowid",
    "get_backend",
    "ilike_sql",
    "ir_module_create_sql",
    "ir_module_table",
    "is_duplicate_object_error",
    "is_serverless_runtime",
    "is_supabase_direct_host",
    "is_transaction_pooler_dsn",
    "load_testing_env",
    "migration_supported",
    "normalize_column_ddl",
    "normalize_dsn",
    "normalize_sql_type",
    "now_sql",
    "nuke_dsn_from_env",
    "prepare_postgres_schema_drop",
    "release_postgres_schema_drop_lock",
    "require_dsn_from_env",
    "require_test_dsn_from_env",
    "reset_schema",
    "resolve_sqlite_dsn_for_runtime",
    "returning_id_clause",
    "serial_primary_key",
    "sqlite_file_path",
    "string_sql_type",
    "supports_create_table_if_not_exists",
    "table_exists",
    "terminate_other_backends",
    "test_dsn_from_env",
    "timestamp_sql_type",
    "to_psycopg_dsn",
    "uses_serverless_schema_wipe",
    "warn_if_poor_nuke_dsn",
]
