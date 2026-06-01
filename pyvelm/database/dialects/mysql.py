"""MySQL / MariaDB dialect helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..capabilities import DialectCapabilities, SchemaResetStrategy

if TYPE_CHECKING:
    from ..adapter import ConnectionAdapter

NAME = "mysql"

CAPABILITIES = DialectCapabilities(
    name=NAME,
    supports_returning=False,
    supports_ilike=False,
    supports_add_column_if_not_exists=False,
    supports_drop_schema=False,
    schema_reset=SchemaResetStrategy.DROP_ALL_TABLES,
    placeholder="%s",
)

PORTABLE_TYPE_MAP = {
    "double precision": "DOUBLE",
    "timestamptz": "TIMESTAMP(6)",
    "timestamp": "TIMESTAMP(6)",
    "boolean": "BOOLEAN",
    "SERIAL": "INTEGER",
}


def normalize_dsn(dsn: str) -> str | None:
    if dsn.startswith("mysql://") and "+pymysql" not in dsn.split(":", 1)[0]:
        return "mysql+pymysql://" + dsn[len("mysql://") :]
    if dsn.startswith("mariadb://") and "+pymysql" not in dsn.split(":", 1)[0]:
        return "mariadb+pymysql://" + dsn[len("mariadb://") :]
    return None


def configure_engine(engine) -> None:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _mysql_on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("SET SESSION sql_mode = 'ANSI_QUOTES'")
        cursor.close()


def serial_primary_key() -> str:
    return '"id" INTEGER NOT NULL AUTO_INCREMENT PRIMARY KEY'


def fetch_lastrowid(conn: ConnectionAdapter, table: str) -> int:
    row = conn.execute("SELECT LAST_INSERT_ID()").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def timestamp_sql_type() -> str:
    return "TIMESTAMP(6)"


def now_sql() -> str:
    return "CURRENT_TIMESTAMP(6)"


def string_sql_type(*, primary_key: bool = False) -> str:
    return "VARCHAR(255)" if primary_key else "TEXT"


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
    return "duplicate column" in msg


def before_reset_all_tables(conn: ConnectionAdapter) -> None:
    conn.execute("SET FOREIGN_KEY_CHECKS = 0")


def after_reset_all_tables(conn: ConnectionAdapter) -> None:
    conn.execute("SET FOREIGN_KEY_CHECKS = 1")
