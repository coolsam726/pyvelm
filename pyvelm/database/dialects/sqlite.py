"""SQLite dialect helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..capabilities import DialectCapabilities, SchemaResetStrategy

if TYPE_CHECKING:
    from ..adapter import ConnectionAdapter

NAME = "sqlite"

CAPABILITIES = DialectCapabilities(
    name=NAME,
    supports_returning=True,
    supports_ilike=False,
    supports_add_column_if_not_exists=False,
    supports_drop_schema=False,
    schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
    placeholder="?",
)

PORTABLE_TYPE_MAP = {
    "double precision": "REAL",
    "timestamptz": "timestamp",
    "SERIAL": "INTEGER",
}


def configure_engine(engine) -> None:
    from ..sqlite3_adapters import register_sqlite3_datetime_adapters

    register_sqlite3_datetime_adapters()


def serial_primary_key() -> str:
    return '"id" INTEGER PRIMARY KEY AUTOINCREMENT'


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    row = conn.execute(f'SELECT MAX("id") FROM "{table}"').fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def timestamp_sql_type() -> str:
    return "timestamp"


def now_sql() -> str:
    return "CURRENT_TIMESTAMP"


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
    from datetime import date, datetime, time

    from ..sqlite3_adapters import adapt_date_iso, adapt_datetime_iso, adapt_time_iso

    out: list[Any] = []
    for value in params:
        if isinstance(value, datetime):
            out.append(adapt_datetime_iso(value))
        elif isinstance(value, date):
            out.append(adapt_date_iso(value))
        elif isinstance(value, time):
            out.append(adapt_time_iso(value))
        else:
            out.append(value)
    return tuple(out)


def is_duplicate_column_error(msg: str) -> bool:
    return "duplicate column" in msg


def before_reset_all_tables(conn: ConnectionAdapter) -> None:
    return None


def after_reset_all_tables(conn: ConnectionAdapter) -> None:
    return None
