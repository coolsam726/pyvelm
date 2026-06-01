"""Dialect capability flags shared across backends."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SchemaResetStrategy(str, Enum):
    DROP_SCHEMA = "drop_schema"
    DROP_ALL_TABLES = "drop_all_tables"
    DELETE_FILE = "delete_file"


@dataclass(frozen=True)
class DialectCapabilities:
    """Backend feature flags used by ORM, domain, and migrate helpers."""

    name: str
    supports_returning: bool
    supports_ilike: bool
    supports_add_column_if_not_exists: bool
    supports_drop_schema: bool
    schema_reset: SchemaResetStrategy
    placeholder: str  # ``%s`` (postgres/psycopg) or ``?`` (sqlite)


def dialect_base_name(dialect_name: str) -> str:
    """Normalise SQLAlchemy dialect names to pyvelm capability keys."""
    name = (dialect_name or "postgresql").split("+", 1)[0].lower()
    if name in ("mariadb", "mysql"):
        return "mysql"
    if name in ("mssql", "sqlserver"):
        return "mssql"
    return name
