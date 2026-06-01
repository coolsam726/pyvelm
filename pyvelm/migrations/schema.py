"""Declarative schema migrations — no hand-written SQL in module scripts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    column as sa_column,
    delete,
    or_,
    select,
    table as sa_table,
    update,
    text as sa_text,
    true as sa_true,
)
from sqlalchemy import and_

from pyvelm.database import conn_capabilities
from pyvelm.database.sa_alter import (
    execute_add_foreign_key,
    execute_create_index,
    execute_drop_column,
    execute_drop_constraint,
    execute_rename_column,
    execute_set_column_nullable,
)
from pyvelm.database.sa_ddl import (
    execute_add_column,
    execute_create_table,
    primary_key_column,
    referenced_tables_from_columns,
    require_sa_connection,
    table_from_columns,
)

if TYPE_CHECKING:
    from pyvelm.env import Environment


class _ColumnSpec:
    """Fluent column definition."""

    __slots__ = (
        "name",
        "col_type",
        "allows_null",
        "_client_default",
        "server_default",
        "fk_table",
        "fk_ondelete",
        "_cap",
    )

    def __init__(self, name: str, col_type, *, cap) -> None:
        self.name = name
        self.col_type = col_type
        self.allows_null = False
        self._client_default = None
        self.server_default = None
        self.fk_table: str | None = None
        self.fk_ondelete = "CASCADE"
        self._cap = cap

    def nullable(self, value: bool = True) -> _ColumnSpec:
        self.allows_null = value
        return self

    def default(self, value: Any) -> _ColumnSpec:
        if isinstance(value, bool):
            self.server_default = sa_true() if value else sa_text("false")
        elif isinstance(value, (int, float)):
            self.server_default = sa_text(str(value))
        elif isinstance(value, str):
            self.server_default = sa_text(repr(value))
        else:
            self._client_default = value
        return self

    def references(self, table_name: str, *, ondelete: str = "CASCADE") -> _ColumnSpec:
        self.fk_table = table_name
        self.fk_ondelete = ondelete
        return self

    def build(self) -> Column:
        fk = None
        if self.fk_table:
            fk = ForeignKey(f"{self.fk_table}.id", ondelete=self.fk_ondelete)
        col = Column(
            self.name,
            self.col_type,
            fk,
            nullable=self.allows_null,
            default=self._client_default,
            server_default=self.server_default,
        )
        return col


@dataclass
class _AlterOp:
    fn: Callable[[str, Any, Any], None]


class Blueprint:
    """Build columns and alterations for one table."""

    def __init__(self, table: str, cap, *, create: bool) -> None:
        self.table = table
        self._cap = cap
        self._create = create
        self._columns: list[Column] = []
        self._constraints: list = []
        self._indexes: list[tuple[str, tuple[str, ...]]] = []
        self._alter_ops: list[_AlterOp] = []

    def id(self, name: str = "id") -> None:
        if not self._create:
            raise RuntimeError("id() is only valid inside schema.create()")
        self._columns.append(primary_key_column(self._cap))

    def string(
        self, name: str, length: int = 255, *, nullable: bool = False
    ) -> _ColumnSpec:
        return self._add_column(name, String(length), nullable=nullable)

    def text(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Text(), nullable=nullable)

    def integer(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Integer(), nullable=nullable)

    def boolean(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Boolean(), nullable=nullable)

    def float(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Float(), nullable=nullable)

    def timestamp(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        from sqlalchemy import DateTime

        return self._add_column(name, DateTime(), nullable=nullable)

    def foreign_id(
        self,
        name: str,
        ref_table: str,
        *,
        ondelete: str = "CASCADE",
        nullable: bool = True,
    ) -> _ColumnSpec:
        spec = (
            _ColumnSpec(name, Integer(), cap=self._cap)
            .nullable(nullable)
            .references(ref_table, ondelete=ondelete)
        )
        col = spec.build()
        if self._create:
            self._columns.append(col)
        else:
            self._alter_ops.append(
                _AlterOp(lambda t, c, col=col: _add_column_if_missing(c, t, col))
            )
        return spec

    def index(self, *column_names: str, name: str | None = None) -> None:
        if not self._create:
            raise RuntimeError("index() is only valid inside schema.create()")
        iname = name or f"{self.table}_{'_'.join(column_names)}_idx"
        self._indexes.append((iname, column_names))

    def primary_key(self, *column_names: str) -> None:
        if not self._create:
            raise RuntimeError("primary_key() is only valid inside schema.create()")
        self._constraints.append(PrimaryKeyConstraint(*column_names))

    def foreign_key(
        self,
        local_column: str,
        ref_table: str,
        *,
        ondelete: str = "CASCADE",
        name: str | None = None,
    ) -> None:
        cname = name or f"{self.table}_{local_column}_fkey"
        if self._create:
            self._constraints.append(
                ForeignKeyConstraint(
                    [local_column],
                    [f"{ref_table}.id"],
                    ondelete=ondelete,
                    name=cname,
                )
            )
        else:
            self._alter_ops.append(
                _AlterOp(
                    lambda t, c, cap, lc=local_column, rt=ref_table, cn=cname, od=ondelete: execute_add_foreign_key(
                        c, t, cn, lc, rt, ondelete=od, cap=cap
                    )
                )
            )

    def drop_column(self, name: str) -> None:
        self._alter_ops.append(
            _AlterOp(lambda t, c, cap, n=name: execute_drop_column(c, t, n, cap=cap))
        )

    def rename_column(self, from_name: str, to_name: str) -> None:
        self._alter_ops.append(
            _AlterOp(
                lambda t, c, cap, a=from_name, b=to_name: execute_rename_column(
                    c, t, a, b, cap=cap
                )
            )
        )

    def drop_nullable(self, name: str) -> None:
        """Make column NOT NULL (drop nullable constraint)."""
        self._alter_ops.append(
            _AlterOp(
                lambda t, c, cap, n=name: execute_set_column_nullable(
                    c, t, n, nullable=False, cap=cap
                )
            )
        )

    def allow_null(self, name: str) -> None:
        """Allow NULL values (DROP NOT NULL)."""
        self._alter_ops.append(
            _AlterOp(
                lambda t, c, cap, n=name: execute_set_column_nullable(
                    c, t, n, nullable=True, cap=cap
                )
            )
        )

    def drop_constraint(self, name: str) -> None:
        self._alter_ops.append(
            _AlterOp(
                lambda t, c, cap, n=name: execute_drop_constraint(c, t, n, cap=cap)
            )
        )

    def _add_column(self, name: str, col_type, *, nullable: bool) -> _ColumnSpec:
        spec = _ColumnSpec(name, col_type, cap=self._cap).nullable(nullable)
        col = spec.build()
        if self._create:
            self._columns.append(col)
        else:
            self._alter_ops.append(
                _AlterOp(lambda t, c, cap, col=col: _add_column_if_missing(c, t, col, cap))
            )
        return spec

    def _run_alters(self, conn, cap) -> None:
        for op in self._alter_ops:
            op.fn(self.table, conn, cap)


def _add_column_if_missing(conn, table: str, col: Column, cap) -> None:
    from pyvelm.database import column_exists

    if column_exists(conn, table, col.name, cap):
        return
    execute_add_column(conn, table, col, cap, if_not_exists=True)


class Schema:
    """``Schema(env).create(...)`` / ``.table(...)`` — Laravel-style migrations."""

    def __init__(self, env: Environment) -> None:
        self.env = env
        self.conn = env.conn
        self.cap = conn_capabilities(env.conn)

    def create(self, table: str, fn: Callable[[Blueprint], None]) -> None:
        bp = Blueprint(table, self.cap, create=True)
        fn(bp)
        cols = list(bp._columns)
        has_pk = any(c.primary_key for c in cols) or any(
            isinstance(c, PrimaryKeyConstraint) for c in bp._constraints
        )
        if not has_pk:
            bp.id()
            cols = list(bp._columns)
        tbl = table_from_columns(
            table,
            cols,
            referenced_tables=referenced_tables_from_columns(cols),
        )
        for constraint in bp._constraints:
            tbl.append_constraint(constraint)
        execute_create_table(self.conn, tbl, cap=self.cap)
        for iname, cols in bp._indexes:
            execute_create_index(self.conn, iname, table, cols, cap=self.cap)

    def table(self, table: str, fn: Callable[[Blueprint], None]) -> None:
        bp = Blueprint(table, self.cap, create=False)
        fn(bp)
        bp._run_alters(self.conn, self.cap)

    def has_column(self, table: str, column: str) -> bool:
        from pyvelm.database import column_exists

        return column_exists(self.conn, table, column, self.cap)

    def row_exists(self, table: str, **filters: Any) -> bool:
        return self._fetchone(table, filters) is not None

    def copy_column(
        self,
        table: str,
        to_column: str,
        from_column: str,
        *,
        only_where_to_null: bool = True,
    ) -> None:
        sa_conn = require_sa_connection(self.conn)
        tbl = sa_table(
            table, sa_column(to_column), sa_column(from_column)
        )
        cond = tbl.c[from_column].isnot(None)
        if only_where_to_null:
            cond = and_(cond, tbl.c[to_column].is_(None))
        sa_conn.execute(
            update(tbl).where(cond).values({to_column: tbl.c[from_column]})
        )

    def copy_column_if_dest_empty(
        self,
        table: str,
        to_column: str,
        from_column: str,
    ) -> None:
        """Copy when dest is NULL or empty string and source is non-empty."""
        sa_conn = require_sa_connection(self.conn)
        tbl = sa_table(
            table, sa_column(to_column), sa_column(from_column)
        )
        dest_empty = or_(tbl.c[to_column].is_(None), tbl.c[to_column] == "")
        cond = and_(
            dest_empty,
            tbl.c[from_column].isnot(None),
            tbl.c[from_column] != "",
        )
        sa_conn.execute(
            update(tbl).where(cond).values({to_column: tbl.c[from_column]})
        )

    def update_rows(self, table: str, values: dict[str, Any], **where: Any) -> None:
        sa_conn = require_sa_connection(self.conn)
        names = list(dict.fromkeys(list(values) + list(where)))
        tbl = sa_table(table, *[sa_column(n) for n in names])
        cond = _where_clause(tbl, where)
        sa_conn.execute(update(tbl).where(cond).values(**values))

    def delete_rows(self, table: str, **where: Any) -> None:
        sa_conn = require_sa_connection(self.conn)
        tbl = sa_table(table, *[sa_column(k) for k in where])
        sa_conn.execute(delete(tbl).where(_where_clause(tbl, where)))

    def _fetchone(self, table: str, filters: dict[str, Any]):
        sa_conn = require_sa_connection(self.conn)
        tbl = sa_table(table, *[sa_column(k) for k in filters])
        stmt = select(tbl).where(_where_clause(tbl, filters)).limit(1)
        return sa_conn.execute(stmt).fetchone()

    def rename_module(self, old_name: str, new_name: str) -> None:
        if self.row_exists("ir_module", name=new_name):
            if self.row_exists("ir_module", name=old_name):
                self.delete_rows("ir_module", name=old_name)
            return
        if self.row_exists("ir_module", name=old_name):
            self.update_rows("ir_module", {"name": new_name}, name=old_name)


def _where_clause(tbl, where: dict[str, Any]):
    parts = []
    for key, val in where.items():
        if val is None:
            parts.append(tbl.c[key].is_(None))
        else:
            parts.append(tbl.c[key] == val)
    return and_(*parts)
