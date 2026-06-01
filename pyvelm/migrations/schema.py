"""Declarative schema migrations — no hand-written SQL in module scripts.

Column builders on :class:`Blueprint` (inside ``schema.create`` / ``schema.table``):

- ``id``, ``string``, ``text``, ``integer``, ``bigInteger`` (alias ``big``)
- ``boolean``, ``float``, ``timestamp``, ``date``, ``time``
- ``foreign_id(name, table, …)`` — integer FK column in one call
- ``foreign(name).constrained(table?)`` / ``foreignId(name)`` — fluent FK (Laravel-style)

Alter helpers: ``drop_column``, ``rename_column``, ``drop_nullable``, ``allow_null``,
``drop_constraint``, ``foreign_key``, ``index``, ``primary_key``.

See :data:`SUPPORTED_COLUMN_BUILDERS` and :data:`SUPPORTED_ALTERATIONS`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

from sqlalchemy import (
    BigInteger,
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

# Public registry of Blueprint builder names (for docs / tooling).
SUPPORTED_COLUMN_BUILDERS: tuple[str, ...] = (
    "id",
    "string",
    "text",
    "integer",
    "bigInteger",
    "big",
    "boolean",
    "float",
    "timestamp",
    "date",
    "time",
    "foreign_id",
    "foreign",
    "foreignId",
)

SUPPORTED_ALTERATIONS: tuple[str, ...] = (
    "drop_column",
    "rename_column",
    "drop_nullable",
    "allow_null",
    "drop_constraint",
    "foreign_key",
    "index",
    "primary_key",
)


def _normalize_ondelete(action: str) -> str:
    key = (action or "CASCADE").strip().upper().replace(" ", "_")
    return {
        "CASCADE": "CASCADE",
        "SET_NULL": "SET NULL",
        "RESTRICT": "RESTRICT",
        "NO_ACTION": "NO ACTION",
        "SET_DEFAULT": "SET DEFAULT",
    }.get(key, key.replace("_", " "))


def _infer_fk_table(column: str) -> str:
    """Guess referenced table from ``{model}_id`` (Laravel ``constrained()`` default).

    ``group_id`` → ``groups``. Pyvelm often uses prefixed tables (``res_company``);
    pass the table explicitly when inference does not match.
    """
    if not column.endswith("_id"):
        raise ValueError(
            f"Cannot infer referenced table from column {column!r}; "
            f"use constrained('table_name')."
        )
    stem = column[:-3]
    if stem.endswith("s"):
        return stem
    return f"{stem}s"


class _ForeignColumnBuilder:
    """Fluent FK column — finish with ``.constrained()`` or ``.references()``."""

    __slots__ = ("_bp", "_name", "_use_big", "_ref_table", "_nullable", "_ondelete")

    def __init__(self, bp: "Blueprint", name: str, *, use_big: bool = False) -> None:
        self._bp = bp
        self._name = name
        self._use_big = use_big
        self._ref_table: str | None = None
        self._nullable = True
        self._ondelete = "CASCADE"

    def constrained(self, table: str | None = None) -> _ColumnSpec:
        ref = table if table is not None else _infer_fk_table(self._name)
        return self._bp._add_foreign_key_column(
            self._name,
            ref,
            nullable=self._nullable,
            ondelete=self._ondelete,
            use_big=self._use_big,
        )

    def references(self, table: str) -> _ColumnSpec:
        """Alias for ``constrained(table)``."""
        return self.constrained(table)

    def nullable(self, value: bool = True) -> _ForeignColumnBuilder:
        self._nullable = value
        return self

    def null(self) -> _ForeignColumnBuilder:
        return self.nullable(True)

    def onDelete(self, action: str) -> _ForeignColumnBuilder:
        self._ondelete = _normalize_ondelete(action)
        return self

    ondelete = onDelete

    def cascade(self) -> _ForeignColumnBuilder:
        return self.onDelete("CASCADE")

    def setNull(self) -> _ForeignColumnBuilder:
        return self.onDelete("SET NULL")


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
        from pyvelm.database.sa_ddl import uses_inline_foreign_keys

        fk = None
        if self.fk_table and uses_inline_foreign_keys(self._cap):
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
    """Build columns and alterations for one table.

    Use :meth:`supported_columns` / :meth:`supported_alterations` to list builders.
    """

    @classmethod
    def supported_columns(cls) -> tuple[str, ...]:
        """Column type builders available on ``schema.create`` / ``schema.table``."""
        return SUPPORTED_COLUMN_BUILDERS

    @classmethod
    def supported_alterations(cls) -> tuple[str, ...]:
        """Table alteration helpers (mostly ``schema.table``)."""
        return SUPPORTED_ALTERATIONS

    def __init__(self, table: str, cap, *, create: bool) -> None:
        self.table = table
        self._cap = cap
        self._create = create
        self._columns: list[Column] = []
        self._constraints: list = []
        self._indexes: list[tuple[str, tuple[str, ...]]] = []
        self._alter_ops: list[_AlterOp] = []
        self._deferred_fks: list[tuple[str, str, str, str]] = []

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

    def bigInteger(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, BigInteger(), nullable=nullable)

    def big(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        """Alias for :meth:`bigInteger`."""
        return self.bigInteger(name, nullable=nullable)

    def boolean(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Boolean(), nullable=nullable)

    def float(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        return self._add_column(name, Float(), nullable=nullable)

    def timestamp(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        from sqlalchemy import DateTime

        return self._add_column(name, DateTime(), nullable=nullable)

    def date(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        from sqlalchemy import Date

        return self._add_column(name, Date(), nullable=nullable)

    def time(self, name: str, *, nullable: bool = True) -> _ColumnSpec:
        from sqlalchemy import Time

        return self._add_column(name, Time(), nullable=nullable)

    def foreign_id(
        self,
        name: str,
        ref_table: str,
        *,
        ondelete: str = "CASCADE",
        nullable: bool = True,
    ) -> _ColumnSpec:
        """Add an integer FK column referencing ``ref_table.id``."""
        return self._add_foreign_key_column(
            name,
            ref_table,
            nullable=nullable,
            ondelete=ondelete,
            use_big=False,
        )

    def foreign(self, name: str, *, big: bool = False) -> _ForeignColumnBuilder:
        """Start a fluent FK column; finish with ``.constrained()`` or ``.references()``."""
        return _ForeignColumnBuilder(self, name, use_big=big)

    def foreignId(self, name: str) -> _ForeignColumnBuilder:
        """``foreign(name, big=True)`` — Laravel-style ``foreignId`` (bigint FK)."""
        return self.foreign(name, big=True)

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
        from pyvelm.database.sa_ddl import uses_inline_foreign_keys

        cname = name or f"{self.table}_{local_column}_fkey"
        if self._create:
            if uses_inline_foreign_keys(self._cap):
                self._constraints.append(
                    ForeignKeyConstraint(
                        [local_column],
                        [f"{ref_table}.id"],
                        ondelete=ondelete,
                        name=cname,
                    )
                )
            else:
                self._deferred_fks.append(
                    (local_column, ref_table, cname, ondelete)
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

    def _add_foreign_key_column(
        self,
        name: str,
        ref_table: str,
        *,
        nullable: bool,
        ondelete: str,
        use_big: bool,
    ) -> _ColumnSpec:
        col_type = BigInteger() if use_big else Integer()
        spec = (
            _ColumnSpec(name, col_type, cap=self._cap)
            .nullable(nullable)
            .references(ref_table, ondelete=ondelete)
        )
        from pyvelm.database.sa_ddl import uses_inline_foreign_keys

        cname = f"{self.table}_{name}_fkey"
        if self._create and not uses_inline_foreign_keys(self._cap):
            self._columns.append(Column(name, col_type, nullable=nullable))
            self._deferred_fks.append((name, ref_table, cname, ondelete))
            return spec
        col = spec.build()
        if self._create:
            self._columns.append(col)
        else:
            bare = Column(name, col_type, nullable=nullable)
            self._alter_ops.append(
                _AlterOp(
                    lambda t, c, cap, col=bare: _add_column_if_missing(c, t, col, cap)
                )
            )
            self._alter_ops.append(
                _AlterOp(
                    lambda t, c, cap, lc=name, rt=ref_table, cn=cname, od=ondelete: execute_add_foreign_key(
                        c, t, cn, lc, rt, ondelete=od, cap=cap
                    )
                )
            )
        return spec

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


# Annotate migration builders for IDE autocomplete (``def _alter(t: Table):``).
Table: TypeAlias = Blueprint
TableCallback: TypeAlias = Callable[[Blueprint], None]

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

    def create(self, table: str, fn: TableCallback) -> None:
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
        for lc, rt, cn, od in bp._deferred_fks:
            execute_add_foreign_key(
                self.conn, table, cn, lc, rt, ondelete=od, cap=self.cap
            )
        for iname, cols in bp._indexes:
            execute_create_index(self.conn, iname, table, cols, cap=self.cap)

    def table(self, table: str, fn: TableCallback) -> None:
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
