"""Schema diff between declared models and the live database.

Compares owned models to Postgres (via ``information_schema``) and reports
anything that warrants a migration or manual DDL — Odoo-style model-driven
detection, not only "column name missing".

**Applied on install/upgrade/migrate** (``apply_schema_diff``)

* New tables and new columns (additive DDL).
* ``SET NOT NULL`` when the model field is required and the column has no NULL rows.
* ``DROP NOT NULL`` when the model field is optional and the column is still strict.

**Detected but not auto-applied**

* ``SET NOT NULL`` while NULL rows still exist (backfill in a migration script first).
* SQL type drift (need ``USING``).
* Orphan columns (in DB, not on model).

**Still hand-written**

* Column renames (shows as orphan + new column).
* M2M junction tables (ORM creates at install).
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import TYPE_CHECKING

from .fields import Field, Many2many, One2many

if TYPE_CHECKING:
    from .env import Environment


# Map Postgres udt_name / data_type to the type strings used in field DDL.
# System columns: always NOT NULL in DDL; never report nullability drift.
_SKIP_ALTERATION_COLUMNS = frozenset({"id"})

_PG_TYPE_NORMALIZE: dict[str, str] = {
    "int4": "integer",
    "int8": "bigint",
    "float8": "double precision",
    "bool": "boolean",
    "text": "text",
    "varchar": "text",
    "bpchar": "text",
    "timestamp": "timestamp",
    "timestamptz": "timestamp",
    "date": "date",
    "time": "time",
    "timetz": "time",
}


@dataclass(frozen=True)
class ColumnSchema:
    nullable: bool
    type_spec: str


@dataclass(frozen=True)
class SchemaAlteration:
    """A model/DB mismatch on an existing column."""

    table: str
    column: str
    kind: str
    detail: str

    def cli_line(self) -> str:
        prefix = f"  ~ {self.table}.{self.column}:"
        if self.kind == "set_not_null":
            return f"{prefix} model required=True, DB allows NULL — {self.detail}"
        if self.kind == "drop_not_null":
            return f"{prefix} model optional, DB is NOT NULL — {self.detail}"
        if self.kind == "type":
            return f"{prefix} type mismatch — {self.detail}"
        return f"{prefix} {self.kind} — {self.detail}"


@dataclass
class Diff:
    """Structured delta between declared models and the DB."""

    new_tables: list[tuple[str, list]] = _dc_field(default_factory=list)
    new_columns: list[tuple[str, str, Field, bool, str]] = _dc_field(default_factory=list)
    orphan_columns: list[tuple[str, str]] = _dc_field(default_factory=list)
    alterations: list[SchemaAlteration] = _dc_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.new_tables
            or self.new_columns
            or self.orphan_columns
            or self.alterations
        )


def diff_has_syncable_changes(env: "Environment", diff: Diff) -> bool:
    """True when ``apply_schema_diff`` would apply at least one change.

    Ignores orphan columns and type drift (hand-written migrations only),
    and ``SET NOT NULL`` while NULL rows still exist.
    """
    if diff.new_tables or diff.new_columns:
        return True
    for alt in diff.alterations:
        if alt.kind == "drop_not_null":
            return True
        if alt.kind == "set_not_null" and not _column_has_nulls(
            env, alt.table, alt.column
        ):
            return True
    return False


def _syncable_summary(diff: Diff) -> str:
    """Human summary of changes Sync can apply (subset of ``_summary``)."""
    if not (
        diff.new_tables
        or diff.new_columns
        or any(
            a.kind in ("set_not_null", "drop_not_null") for a in diff.alterations
        )
    ):
        return ""
    parts: list[str] = []
    if diff.new_tables:
        parts.append(f"{len(diff.new_tables)} new table(s)")
    if diff.new_columns:
        parts.append(f"{len(diff.new_columns)} new column(s)")
    kinds: dict[str, int] = {}
    for alt in diff.alterations:
        if alt.kind in ("set_not_null", "drop_not_null"):
            kinds[alt.kind] = kinds.get(alt.kind, 0) + 1
    labels: list[str] = []
    if kinds.get("set_not_null"):
        labels.append(f"{kinds['set_not_null']} NOT NULL tighten")
    if kinds.get("drop_not_null"):
        labels.append(f"{kinds['drop_not_null']} NOT NULL relax")
    if labels:
        parts.append(", ".join(labels) + " change(s)")
    return "Changes: " + ", ".join(parts) + "."


def _field_type_spec(field: Field) -> str:
    """Normalized SQL type string for a stored field declaration."""
    return _normalize_type_name(getattr(field, "sql_type", "text"))


def _normalize_type_name(type_name: str) -> str:
    key = (type_name or "text").strip().lower()
    return _PG_TYPE_NORMALIZE.get(key, key)


def _normalize_pg_column(udt_name: str, data_type: str) -> str:
    udt = (udt_name or "").strip().lower()
    if udt in _PG_TYPE_NORMALIZE:
        return _PG_TYPE_NORMALIZE[udt]
    return (data_type or udt or "text").strip().lower()


def _varchar_family(type_name: str) -> bool:
    """True for Char-like types (varchar/text) that are compatible in Postgres."""
    key = _normalize_type_name(type_name)
    if key in ("text", "character varying", "varchar"):
        return True
    return key.startswith("varchar(") or key.startswith("character varying")


def _types_match(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if _varchar_family(expected) and _varchar_family(actual):
        return True
    return False


def compute_diff(env: "Environment", module: str) -> Diff:
    """Diff the live DB schema against models owned by ``module``."""
    diff = Diff()
    reg = env.registry
    owned = sorted(
        name for name, owner in reg._model_module.items() if owner == module
    )
    for model_name in owned:
        cls = reg[model_name]
        table = cls._table
        cap = getattr(env.conn, "capabilities", None)
        if cap is None:
            from .database import dialect_capabilities

            cap = dialect_capabilities("postgresql")
        from .database.sa_ddl import model_table_columns

        expected: dict[str, Field] = {}
        for f in cls._fields.values():
            if not f.is_stored:
                continue
            if isinstance(f, (One2many, Many2many)):
                continue
            if f.name == "id" or f.column == "id":
                continue
            expected[f.column] = f
        actual = _fetch_table_columns(env, table)
        if not actual:
            diff.new_tables.append((table, model_table_columns(cls, reg, cap)))
            continue
        for col, field_obj in expected.items():
            if col not in actual:
                was_required = bool(getattr(field_obj, "required", False))
                diff.new_columns.append(
                    (table, col, field_obj, was_required, _field_type_spec(field_obj))
                )
                continue
            db_col = actual[col]
            if col in _SKIP_ALTERATION_COLUMNS:
                continue
            wants_required = bool(
                field_obj and getattr(field_obj, "required", False)
            )
            if wants_required and db_col.nullable:
                diff.alterations.append(
                    SchemaAlteration(
                        table,
                        col,
                        "set_not_null",
                        "backfill NULLs, then SET NOT NULL",
                    )
                )
            elif not wants_required and not db_col.nullable:
                diff.alterations.append(
                    SchemaAlteration(
                        table,
                        col,
                        "drop_not_null",
                        "ALTER COLUMN DROP NOT NULL",
                    )
                )
            expected_type = _field_type_spec(field_obj)
            if not _types_match(expected_type, db_col.type_spec):
                diff.alterations.append(
                    SchemaAlteration(
                        table,
                        col,
                        "type",
                        f"model {expected_type!r}, DB {db_col.type_spec!r}",
                    )
                )
        for col in actual:
            if col == "id":
                continue
            if col not in expected:
                diff.orphan_columns.append((table, col))
    return diff


def _fetch_table_columns(env, table: str) -> dict[str, ColumnSchema] | None:
    """Column name → schema snapshot, or ``None`` if the table is missing."""
    conn = env.conn
    cap = getattr(conn, "capabilities", None)
    sa = getattr(conn, "_sa", None)
    if cap is not None and sa is not None:
        try:
            from sqlalchemy.engine import Connection

            if isinstance(sa, Connection):
                return _fetch_table_columns_inspector(conn, table)
        except ImportError:
            pass
    rows = env.conn.execute(
        "SELECT column_name, is_nullable, udt_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchall()
    if rows:
        out: dict[str, ColumnSchema] = {}
        for name, is_nullable, udt_name, data_type in rows:
            out[name] = ColumnSchema(
                nullable=(is_nullable == "YES"),
                type_spec=_normalize_pg_column(udt_name, data_type),
            )
        return out
    exists = env.conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    ).fetchone()
    return {} if exists else None


def _normalize_inspector_type(col_type) -> str:
    name = type(col_type).__name__.lower()
    mapping = {
        "integer": "integer",
        "bigint": "bigint",
        "boolean": "boolean",
        "float": "double precision",
        "double": "double precision",
        "string": "text",
        "text": "text",
        "datetime": "timestamp",
        "date": "date",
        "time": "time",
        "numeric": "numeric",
    }
    for key, norm in mapping.items():
        if key in name:
            return norm
    return "text"


def _fetch_table_columns_inspector(conn, table: str) -> dict[str, ColumnSchema] | None:
    cap = getattr(conn, "capabilities", None)
    if cap is not None and cap.name == "sqlite":
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = %s",
            (table,),
        ).fetchone()
        if not row:
            return None
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        out: dict[str, ColumnSchema] = {}
        for _cid, name, col_type, notnull, _default, _pk in rows:
            out[name] = ColumnSchema(
                nullable=not bool(notnull),
                type_spec=(col_type or "text").lower(),
            )
        return out
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import NoSuchTableError

    # Inspect the live connection, not the engine: inspecting the engine
    # opens a second pooled connection that deadlocks on Postgres against an
    # uncommitted ALTER TABLE held by this connection (ACCESS EXCLUSIVE lock).
    from pyvelm.database.introspection import _inspector_table_name

    insp = sa_inspect(conn._sa)
    resolved = _inspector_table_name(insp, table)
    if resolved is None:
        return None
    out: dict[str, ColumnSchema] = {}
    try:
        cols = insp.get_columns(resolved)
    except NoSuchTableError:
        return None
    for col in cols:
        out[col["name"]] = ColumnSchema(
            nullable=bool(col.get("nullable", True)),
            type_spec=_normalize_inspector_type(col["type"]),
        )
    return out


# ---- rendering -------------------------------------------------------


def render_migration(
    diff: Diff,
    from_version: tuple[int, ...],
    to_version: tuple[int, ...],
) -> str:
    """Render the migration file's source as a string."""
    from_str = ".".join(str(p) for p in from_version)
    to_str = ".".join(str(p) for p in to_version)
    out: list[str] = []
    out.append(f'"""Autogenerated migration {from_str} → {to_str}.')
    out.append("")
    out.append(_summary(diff))
    out.append("")
    out.append("Idempotent: every ADD / CREATE uses IF NOT EXISTS.")
    out.append("Type / NOT NULL / DROP changes are commented — review first.")
    out.append('"""')
    out.append("")
    out.append("from pyvelm.migrations import Schema, Table")
    out.append("")
    out.append("")
    out.append("def upgrade(env):")
    if diff.is_empty:
        out.append("    pass  # nothing to do")
        return "\n".join(out) + "\n"
    out.append("    schema = Schema(env)")
    for table, columns in diff.new_tables:
        fn_name = f"_{table}"
        out.append("")
        lines = _blueprint_lines_from_columns(columns)
        out.append(f"    def {fn_name}(t: Table) -> None:")
        if lines:
            for line in lines:
                out.append(f"        {line}")
        else:
            out.append("        pass")
        out.append(f"    schema.create({table!r}, {fn_name})")
    for table, col, field_obj, was_required, _sql_type in diff.new_columns:
        fn_name = f"_{table}_add_{col}"
        line = _blueprint_line_from_field(field_obj, col, required=was_required)
        out.append("")
        out.append(f"    def {fn_name}(t: Table) -> None:")
        out.append(f"        {line}")
        out.append(f"    schema.table({table!r}, {fn_name})")
        if was_required:
            out.append(
                f"    # TODO: backfill {table}.{col} then "
                f"schema.table({table!r}, lambda t: t.drop_nullable({col!r}))"
            )
    for alt in diff.alterations:
        out.append("")
        out.append(f"    # {alt.table}.{alt.column}: {alt.kind} — {alt.detail}")
        if alt.kind == "set_not_null":
            out.append(
                f"    # schema.table({alt.table!r}, "
                f"lambda t: t.drop_nullable({alt.column!r}))"
            )
        elif alt.kind == "drop_not_null":
            out.append(
                f"    # schema.table({alt.table!r}, "
                f"lambda t: t.allow_null({alt.column!r}))"
            )
        elif alt.kind == "type":
            out.append(
                f"    # Review type change on {alt.table}.{alt.column} manually"
            )
    if diff.orphan_columns:
        out.append("")
        out.append("    # Orphan columns — review before uncommenting:")
        for table, col in diff.orphan_columns:
            out.append(
                f"    # schema.table({table!r}, lambda t: t.drop_column({col!r}))"
            )
    return "\n".join(out) + "\n"


def _blueprint_lines_from_columns(columns) -> list[str]:
    from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
    from sqlalchemy import Column as SAColumn

    lines: list[str] = []
    for col in columns:
        if not isinstance(col, SAColumn):
            continue
        if col.primary_key:
            continue
        name = col.name
        if col.foreign_keys:
            ref = next(iter(col.foreign_keys)).column.table.name
            ondelete = next(iter(col.foreign_keys)).ondelete or "CASCADE"
            lines.append(
                f"t.foreign_id({name!r}, {ref!r}, ondelete={ondelete!r}, "
                f"nullable={col.nullable})"
            )
            continue
        nullable = col.nullable
        if isinstance(col.type, String):
            lines.append(f"t.string({name!r}, nullable={nullable})")
        elif isinstance(col.type, Text):
            lines.append(f"t.text({name!r}, nullable={nullable})")
        elif isinstance(col.type, Integer):
            lines.append(f"t.integer({name!r}, nullable={nullable})")
        elif isinstance(col.type, Boolean):
            lines.append(f"t.boolean({name!r}, nullable={nullable})")
        elif isinstance(col.type, DateTime):
            lines.append(f"t.timestamp({name!r}, nullable={nullable})")
        elif isinstance(col.type, Float):
            lines.append(f"t.float({name!r}, nullable={nullable})")
        else:
            lines.append(f"t.text({name!r}, nullable={nullable})")
    return lines


def _blueprint_line_from_field(field: Field, col_name: str, *, required: bool) -> str:
    from .fields import Boolean as BoolField
    from .fields import Char, Float, Integer, Many2one, Text

    nullable = not required
    if isinstance(field, Char):
        return f"t.string({col_name!r}, nullable={nullable})"
    if isinstance(field, Text):
        return f"t.text({col_name!r}, nullable={nullable})"
    if isinstance(field, Integer):
        return f"t.integer({col_name!r}, nullable={nullable})"
    if isinstance(field, BoolField):
        return f"t.boolean({col_name!r}, nullable={nullable})"
    if isinstance(field, Float):
        return f"t.float({col_name!r}, nullable={nullable})"
    if isinstance(field, Many2one):
        comodel = getattr(field, "comodel", "unknown")
        table = comodel.replace(".", "_")
        ondelete = getattr(field, "ondelete", "SET NULL") or "SET NULL"
        return (
            f"t.foreign_id({col_name!r}, {table!r}, ondelete={ondelete!r}, "
            f"nullable={nullable})"
        )
    return f"t.text({col_name!r}, nullable={nullable})"


def _summary(diff: Diff) -> str:
    if diff.is_empty:
        return "Changes: none."
    parts: list[str] = []
    if diff.new_tables:
        parts.append(f"{len(diff.new_tables)} new table(s)")
    if diff.new_columns:
        parts.append(f"{len(diff.new_columns)} new column(s)")
    if diff.alterations:
        kinds = {}
        for a in diff.alterations:
            kinds[a.kind] = kinds.get(a.kind, 0) + 1
        labels = []
        if kinds.get("type"):
            labels.append(f"{kinds['type']} type")
        if kinds.get("set_not_null"):
            labels.append(f"{kinds['set_not_null']} NOT NULL tighten")
        if kinds.get("drop_not_null"):
            labels.append(f"{kinds['drop_not_null']} NOT NULL relax")
        parts.append(", ".join(labels) + " change(s)")
    if diff.orphan_columns:
        parts.append(f"{len(diff.orphan_columns)} orphan column(s)")
    return "Changes: " + ", ".join(parts) + "."


def _q(s: str) -> str:
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---- version helpers -------------------------------------------------


def next_minor_version(version: tuple[int, ...]) -> tuple[int, ...]:
    parts = list(version)
    while len(parts) < 2:
        parts.append(0)
    parts[1] += 1
    if len(parts) >= 3:
        parts[2] = 0
    return tuple(parts)


def migration_filename(
    from_version: tuple[int, ...], to_version: tuple[int, ...]
) -> str:
    def _join(v: tuple[int, ...]) -> str:
        parts = list(v)
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return "_".join(str(p) for p in parts)

    return f"{_join(from_version)}_to_{_join(to_version)}.py"


def parse_version(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split("."))


@dataclass
class ApplyResult:
    new_tables: int = 0
    new_columns: int = 0
    set_not_null: int = 0
    drop_not_null: int = 0
    skipped_not_null: int = 0
    skipped_not_null_cols: list[str] = _dc_field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            self.new_tables == 0
            and self.new_columns == 0
            and self.set_not_null == 0
            and self.drop_not_null == 0
            and self.skipped_not_null == 0
        )

    def summary(self) -> str:
        if self.is_empty:
            return "schema unchanged"
        parts: list[str] = []
        if self.new_tables:
            parts.append(f"{self.new_tables} table(s)")
        if self.new_columns:
            parts.append(f"{self.new_columns} column(s)")
        if self.set_not_null:
            parts.append(f"{self.set_not_null} NOT NULL")
        if self.drop_not_null:
            parts.append(f"{self.drop_not_null} relaxed")
        if self.skipped_not_null_cols:
            cols = ", ".join(self.skipped_not_null_cols)
            parts.append(f"NOT NULL pending on {cols} (NULL rows — backfill)")
        elif self.skipped_not_null:
            parts.append(
                f"{self.skipped_not_null} NOT NULL pending (NULL rows — backfill)"
            )
        return "schema: " + ", ".join(parts) + "."


def count_null_rows(env: "Environment", table: str, column: str) -> int:
    """How many rows have NULL in *column* (blocks ``SET NOT NULL``)."""
    from pyvelm.database.sa_ddl import count_null_rows as _count_null_rows

    return _count_null_rows(env.conn, table, column)


def _column_has_nulls(env: "Environment", table: str, column: str) -> bool:
    return count_null_rows(env, table, column) > 0


def _apply_nullability(
    env: "Environment", diff: Diff, result: ApplyResult
) -> None:
    from pyvelm.database import _conn_capabilities, normalize_sql_type
    from pyvelm.database.sa_ddl import execute_sql

    cap = _conn_capabilities(env.conn)
    if cap.name in ("sqlite", "mysql"):
        return
    for alt in diff.alterations:
        if alt.kind == "set_not_null":
            if _column_has_nulls(env, alt.table, alt.column):
                result.skipped_not_null += 1
                n = count_null_rows(env, alt.table, alt.column)
                result.skipped_not_null_cols.append(
                    f"{alt.table}.{alt.column} ({n} NULL)"
                )
                continue
            if cap.name == "oracle":
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" MODIFY ("{alt.column}" NOT NULL)',
                )
            elif cap.name == "mssql":
                cols = _fetch_table_columns(env, alt.table) or {}
                col_schema = cols.get(alt.column)
                type_spec = col_schema.type_spec if col_schema is not None else "text"
                sql_type = normalize_sql_type(type_spec, cap)
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" {sql_type} NOT NULL',
                )
            else:
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" SET NOT NULL',
                )
            result.set_not_null += 1
        elif alt.kind == "drop_not_null":
            if cap.name == "oracle":
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" MODIFY ("{alt.column}" NULL)',
                )
            elif cap.name == "mssql":
                cols = _fetch_table_columns(env, alt.table) or {}
                col_schema = cols.get(alt.column)
                type_spec = col_schema.type_spec if col_schema is not None else "text"
                sql_type = normalize_sql_type(type_spec, cap)
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" {sql_type} NULL',
                )
            else:
                execute_sql(
                    env.conn,
                    f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" DROP NOT NULL',
                )
            result.drop_not_null += 1


def _column_exists(env, table: str, column: str) -> bool:
    from pyvelm.database import column_exists

    return column_exists(env.conn, table, column)


def _model_cls_for_table(registry, table: str):
    for cls in registry._models.values():
        if getattr(cls, "_table", None) == table:
            return cls
    return None


def apply_schema_diff(env: "Environment", module: str) -> ApplyResult:
    """Apply model/DB drift: additive DDL plus safe nullability changes."""
    from pyvelm.database import _conn_capabilities, get_backend
    from pyvelm.database.introspection import clear_reflection_cache

    clear_reflection_cache(env.conn)
    diff = compute_diff(env, module)
    result = ApplyResult(
        new_tables=len(diff.new_tables),
        new_columns=len(diff.new_columns),
    )
    from pyvelm.database import is_duplicate_object_error
    from pyvelm.database.sa_ddl import (
        execute_add_column,
        execute_create_table,
        model_table_columns,
        referenced_tables_from_columns,
        table_from_columns,
    )

    cap = _conn_capabilities(env.conn)
    for table, columns in diff.new_tables:
        try:
            tbl = table_from_columns(
                table,
                columns,
                referenced_tables=referenced_tables_from_columns(columns),
                cap=cap,
            )
            execute_create_table(env.conn, tbl, cap=cap)
        except Exception as exc:
            # Backends without CREATE TABLE IF NOT EXISTS (Oracle, MSSQL) raise
            # when the table already exists and their inspectors can disagree
            # with the live schema; treat a duplicate as already-applied and
            # let the column-sync pass below reconcile any drift.
            if not is_duplicate_object_error(exc):
                raise
    clear_reflection_cache(env.conn)
    # Always re-diff after CREATE TABLE attempts. If an inspector race reported
    # "table missing" but CREATE collided with an existing table, the original
    # diff contains no new_columns (it short-circuits at new_tables). A fresh
    # diff is required so we still add any columns that are genuinely missing.
    diff = compute_diff(env, module)
    from pyvelm.database import table_exists

    for table, col, field_obj, _was_required, _sql_type in diff.new_columns:
        if _column_exists(env, table, col):
            continue
        if not table_exists(env.conn, table, cap):
            cls = _model_cls_for_table(env.registry, table)
            if cls is not None:
                try:
                    cols = model_table_columns(cls, env.registry, cap)
                    tbl = table_from_columns(
                        table,
                        cols,
                        referenced_tables=referenced_tables_from_columns(cols),
                        cap=cap,
                    )
                    execute_create_table(env.conn, tbl, cap=cap)
                    clear_reflection_cache(env.conn)
                except Exception as exc:
                    if not is_duplicate_object_error(exc):
                        raise
            continue
        try:
            execute_add_column(
                env.conn,
                table,
                field_obj.sa_column(env.registry, cap),
                cap,
                if_not_exists=cap.supports_add_column_if_not_exists,
            )
        except Exception as exc:
            orig = getattr(exc, "orig", exc)
            msg = str(orig).lower()
            backend = get_backend(cap.name)
            if backend.is_duplicate_column_error(msg):
                continue
            missing = getattr(backend, "is_missing_table_error", None)
            if missing is not None and missing(msg):
                continue
            raise
    clear_reflection_cache(env.conn)
    # Re-diff so new columns can receive SET NOT NULL in the same pass.
    diff = compute_diff(env, module)
    _apply_nullability(env, diff, result)
    return result
