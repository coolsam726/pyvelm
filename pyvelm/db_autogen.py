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

    new_tables: list[tuple[str, str]] = _dc_field(default_factory=list)
    new_columns: list[tuple[str, str, str, bool]] = _dc_field(default_factory=list)
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


def _types_match(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    # Char/Text both land as text in pyvelm + Postgres.
    if expected == "text" and actual in ("text", "character varying", "varchar"):
        return True
    if actual == "text" and expected in ("text", "character varying", "varchar"):
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
        expected: dict[str, tuple[Field, str]] = {}
        for f in cls._fields.values():
            if not f.is_stored:
                continue
            if isinstance(f, (One2many, Many2many)):
                continue
            expected[f.column] = (f, f.column_ddl())
        actual = _fetch_table_columns(env, table)
        if actual is None:
            col_ddls = ['"id" SERIAL PRIMARY KEY'] + [
                ddl for _, ddl in expected.values()
            ]
            ddl = (
                f'CREATE TABLE IF NOT EXISTS "{table}" '
                f'({", ".join(col_ddls)})'
            )
            diff.new_tables.append((table, ddl))
            continue
        for col, (field_obj, col_ddl) in expected.items():
            if col not in actual:
                was_required = bool(
                    field_obj and getattr(field_obj, "required", False)
                )
                safe_ddl = col_ddl.rstrip()
                if safe_ddl.upper().endswith("NOT NULL"):
                    safe_ddl = safe_ddl[: -len("NOT NULL")].rstrip()
                stmt = (
                    f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {safe_ddl}'
                )
                diff.new_columns.append((table, col, stmt, was_required))
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
    out.append("")
    out.append("def migrate(env):")
    if diff.is_empty:
        out.append("    pass  # nothing to do")
        return "\n".join(out) + "\n"
    for _, ddl in diff.new_tables:
        out.append(f"    env.conn.execute({_q(ddl)})")
    for table, col, stmt, was_required in diff.new_columns:
        out.append(f"    env.conn.execute({_q(stmt)})")
        if was_required:
            out.append(
                f"    # TODO: required field — backfill {table}.{col} "
                f"then issue:"
            )
            tighten = (
                f'ALTER TABLE "{table}" ALTER COLUMN "{col}" SET NOT NULL'
            )
            out.append(f"    # env.conn.execute({_q(tighten)})")
    for alt in diff.alterations:
        out.append("")
        out.append(f"    # {alt.table}.{alt.column}: {alt.kind} — {alt.detail}")
        if alt.kind == "set_not_null":
            stmt = (
                f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" '
                f"SET NOT NULL"
            )
            out.append(f"    # env.conn.execute({_q(stmt)})")
        elif alt.kind == "drop_not_null":
            stmt = (
                f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" '
                f"DROP NOT NULL"
            )
            out.append(f"    # env.conn.execute({_q(stmt)})")
        elif alt.kind == "type":
            out.append(
                f"    # e.g. ALTER TABLE \"{alt.table}\" ALTER COLUMN "
                f"\"{alt.column}\" TYPE <new_type> USING ..."
            )
    if diff.orphan_columns:
        out.append("")
        out.append("    # Orphan columns — review before uncommenting:")
        for table, col in diff.orphan_columns:
            drop = f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{col}"'
            out.append(f"    # env.conn.execute({_q(drop)})")
    return "\n".join(out) + "\n"


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
    row = env.conn.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL'
    ).fetchone()
    return int(row[0]) if row else 0


def _column_has_nulls(env: "Environment", table: str, column: str) -> bool:
    return count_null_rows(env, table, column) > 0


def _apply_nullability(
    env: "Environment", diff: Diff, result: ApplyResult
) -> None:
    for alt in diff.alterations:
        if alt.kind == "set_not_null":
            if _column_has_nulls(env, alt.table, alt.column):
                result.skipped_not_null += 1
                n = count_null_rows(env, alt.table, alt.column)
                result.skipped_not_null_cols.append(
                    f"{alt.table}.{alt.column} ({n} NULL)"
                )
                continue
            env.conn.execute(
                f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" '
                f"SET NOT NULL"
            )
            result.set_not_null += 1
        elif alt.kind == "drop_not_null":
            env.conn.execute(
                f'ALTER TABLE "{alt.table}" ALTER COLUMN "{alt.column}" '
                f"DROP NOT NULL"
            )
            result.drop_not_null += 1


def apply_schema_diff(env: "Environment", module: str) -> ApplyResult:
    """Apply model/DB drift: additive DDL plus safe nullability changes."""
    diff = compute_diff(env, module)
    result = ApplyResult(
        new_tables=len(diff.new_tables),
        new_columns=len(diff.new_columns),
    )
    for _, ddl in diff.new_tables:
        env.conn.execute(ddl)
    for _table, _col, stmt, _was_required in diff.new_columns:
        env.conn.execute(stmt)
    # Re-diff so new columns can receive SET NOT NULL in the same pass.
    diff = compute_diff(env, module)
    _apply_nullability(env, diff, result)
    return result
