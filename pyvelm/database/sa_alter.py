"""Portable ALTER helpers via SQLAlchemy Core compilation where possible."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.schema import CreateColumn

from .adapter import conn_capabilities
from .dialects import get_backend
from .introspection import column_exists
from .sa_ddl import _sqlalchemy_dialect, ddl_quote_identifier, require_sa_connection


def compile_create_index(
    name: str, table: str, columns: tuple[str, ...], cap
) -> str:
    cols = ", ".join(f'"{c}"' for c in columns)
    if cap.name in ("postgresql", "sqlite"):
        return f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})'
    if cap.name == "mysql":
        return f'CREATE INDEX "{name}" ON "{table}" ({cols})'
    return f'CREATE INDEX "{name}" ON "{table}" ({cols})'


def compile_create_unique(
    name: str, table: str, columns: tuple[str, ...], cap
) -> str:
    cols = ", ".join(f'"{c}"' for c in columns)
    if cap.name in ("postgresql", "sqlite"):
        return (
            f'CREATE UNIQUE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})'
        )
    if cap.name == "mysql":
        return f'CREATE UNIQUE INDEX "{name}" ON "{table}" ({cols})'
    return f'CREATE UNIQUE INDEX "{name}" ON "{table}" ({cols})'


def compile_drop_column(table: str, column: str, cap) -> str:
    tbl = ddl_quote_identifier(table, cap)
    col = ddl_quote_identifier(column, cap)
    if cap.name in ("postgresql", "sqlite"):
        return f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS {col}"
    if cap.name == "mssql":
        return f"ALTER TABLE {tbl} DROP COLUMN {col}"
    return f"ALTER TABLE {tbl} DROP COLUMN {col}"


def compile_rename_column(table: str, old: str, new: str, cap) -> str:
    if cap.name == "mssql":
        return (
            f"EXEC sp_rename '{table}.{old}', '{new}', 'COLUMN'"
        )
    return f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'


def compile_drop_constraint(table: str, name: str, cap) -> str:
    if cap.name == "oracle":
        return f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"'
    return f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'


def compile_add_foreign_key(
    table: str,
    constraint_name: str,
    local_col: str,
    ref_table: str,
    *,
    ondelete: str = "CASCADE",
    cap,
) -> str:
    if cap.name in ("mssql", "oracle"):
        add_kw = "ADD"
    else:
        add_kw = "ADD CONSTRAINT"
    tbl = ddl_quote_identifier(table, cap)
    cname = ddl_quote_identifier(constraint_name, cap)
    lcol = ddl_quote_identifier(local_col, cap)
    ref = ddl_quote_identifier(ref_table, cap)
    rid = ddl_quote_identifier("id", cap)
    return (
        f"ALTER TABLE {tbl} {add_kw} {cname} "
        f"FOREIGN KEY ({lcol}) REFERENCES {ref}({rid}) "
        f"ON DELETE {ondelete}"
    )


def compile_set_nullable(
    table: str, column: str, *, nullable: bool, cap, type_spec: str | None = None
) -> str:
    if nullable:
        if cap.name == "oracle":
            return f'ALTER TABLE "{table}" MODIFY ("{column}" NULL)'
        if cap.name == "mssql":
            sql_type = type_spec or "text"
            tbl = ddl_quote_identifier(table, cap)
            col = ddl_quote_identifier(column, cap)
            return f"ALTER TABLE {tbl} ALTER COLUMN {col} {sql_type} NULL"
        return f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL'
    if cap.name == "oracle":
        return f'ALTER TABLE "{table}" MODIFY ("{column}" NOT NULL)'
    if cap.name == "mssql":
        sql_type = type_spec or "text"
        tbl = ddl_quote_identifier(table, cap)
        col = ddl_quote_identifier(column, cap)
        return f"ALTER TABLE {tbl} ALTER COLUMN {col} {sql_type} NOT NULL"
    return f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL'


def execute_create_index(
    conn,
    name: str,
    table: str,
    columns: tuple[str, ...],
    *,
    cap=None,
) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(
        text(compile_create_index(name, table, columns, cap))
    )


def execute_create_unique(
    conn,
    name: str,
    table: str,
    columns: tuple[str, ...],
    *,
    cap=None,
) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(
        text(compile_create_unique(name, table, columns, cap))
    )


def execute_drop_column(conn, table: str, column: str, *, cap=None) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(text(compile_drop_column(table, column, cap)))


def execute_rename_column(
    conn, table: str, old: str, new: str, *, cap=None
) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(
        text(compile_rename_column(table, old, new, cap))
    )


def execute_drop_constraint(conn, table: str, name: str, *, cap=None) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(
        text(compile_drop_constraint(table, name, cap))
    )


def execute_add_foreign_key(
    conn,
    table: str,
    constraint_name: str,
    local_col: str,
    ref_table: str,
    *,
    ondelete: str = "CASCADE",
    cap=None,
) -> None:
    cap = cap or conn_capabilities(conn)
    require_sa_connection(conn).execute(
        text(
            compile_add_foreign_key(
                table,
                constraint_name,
                local_col,
                ref_table,
                ondelete=ondelete,
                cap=cap,
            )
        )
    )


def execute_set_column_nullable(
    conn,
    table: str,
    column: str,
    *,
    nullable: bool,
    cap=None,
    type_spec: str | None = None,
) -> None:
    cap = cap or conn_capabilities(conn)
    if type_spec is None and cap.name == "mssql":
        from sqlalchemy import inspect as sa_inspect

        sa_conn = require_sa_connection(conn)
        cols = sa_inspect(sa_conn).get_columns(table)
        for col in cols:
            if col["name"] == column:
                type_spec = str(col["type"])
                break
    require_sa_connection(conn).execute(
        text(compile_set_nullable(table, column, nullable=nullable, cap=cap, type_spec=type_spec))
    )
