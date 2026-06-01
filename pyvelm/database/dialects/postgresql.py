"""PostgreSQL dialect helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..capabilities import DialectCapabilities, SchemaResetStrategy

if TYPE_CHECKING:
    from ..adapter import ConnectionAdapter

NAME = "postgresql"

CAPABILITIES = DialectCapabilities(
    name=NAME,
    supports_returning=True,
    supports_ilike=True,
    supports_add_column_if_not_exists=True,
    supports_drop_schema=True,
    schema_reset=SchemaResetStrategy.DROP_SCHEMA,
    placeholder="%s",
)

PORTABLE_TYPE_MAP: dict[str, str] = {}


def normalize_dsn(dsn: str) -> str | None:
    if dsn.startswith("postgres://"):
        return "postgresql+psycopg://" + dsn[len("postgres://") :]
    if dsn.startswith("postgresql://") and "+psycopg" not in dsn.split(":", 1)[0]:
        return "postgresql+psycopg://" + dsn[len("postgresql://") :]
    return None


def configure_engine(engine) -> None:
    return None


def serial_primary_key() -> str:
    return '"id" SERIAL PRIMARY KEY'


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    row = conn.execute(f'SELECT MAX("id") FROM "{table}"').fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def timestamp_sql_type() -> str:
    return "timestamptz"


def now_sql() -> str:
    return "now()"


def string_sql_type(*, primary_key: bool = False) -> str:
    return "text"


def supports_create_table_if_not_exists() -> bool:
    return True


def append_search_pagination(
    sql: str,
    *,
    base_table_sql: str,
    limit: int | None,
    offset: int,
    order: str | None,
) -> str:
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    if offset:
        sql += f" OFFSET {int(offset)}"
    return sql


def bind_params(params: tuple) -> tuple:
    return params


def is_duplicate_column_error(msg: str) -> bool:
    return False


def before_reset_all_tables(conn: ConnectionAdapter) -> None:
    return None


def after_reset_all_tables(conn: ConnectionAdapter) -> None:
    return None
