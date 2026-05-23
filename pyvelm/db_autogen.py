"""Additive schema-migration autogen.

Compares the loaded model declarations against the live DB schema and
emits a migration file for new columns / tables. Orphan columns (DB
has them, no field declares them) are surfaced as commented-out
``DROP COLUMN`` statements so they need human review.

NOT NULL handling
-----------------
``ADD COLUMN ... NOT NULL`` fails in Postgres when the table already
has rows (no implicit default). The autogen therefore **strips
NOT NULL** from every ADD COLUMN it emits — newly-added columns are
always nullable. For ``required=True`` fields, a ``# TODO`` line is
appended near the statement so the operator remembers to backfill
and re-tighten with ``ALTER TABLE ... ALTER COLUMN ... SET NOT NULL``
once the data is filled in. ``CREATE TABLE`` keeps NOT NULL because
the table is empty by construction.

Out of scope — keep these hand-written:

* Column renames (autogen would emit drop + add, losing data).
* Type changes (would need ``USING`` clauses).
* Seeded-row renames / data backfills (e.g. the "ECB rate fetcher"
  → "Currency Rate Sync from ECB" migration).
* Many2many junction tables (handled by the ORM at install time via
  ``_setup_relation_tables``).
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import TYPE_CHECKING

from .fields import Many2many, One2many

if TYPE_CHECKING:
    from .env import Environment


@dataclass
class Diff:
    """Structured delta between declared models and the DB."""

    new_tables: list[tuple[str, str]] = _dc_field(default_factory=list)
    """List of (table_name, full CREATE TABLE ddl)."""

    new_columns: list[tuple[str, str, str, bool]] = _dc_field(default_factory=list)
    """List of (table_name, column_name, ALTER TABLE ddl, was_required).

    ``was_required`` is True when the field carries ``required=True`` —
    the rendered DDL has its NOT NULL stripped (additive-safe) but the
    flag drives a ``# TODO: backfill + SET NOT NULL`` comment so the
    operator remembers to finish the job.
    """

    orphan_columns: list[tuple[str, str]] = _dc_field(default_factory=list)
    """List of (table_name, column_name) — DB has them, no field does."""

    @property
    def is_empty(self) -> bool:
        return not (self.new_tables or self.new_columns or self.orphan_columns)


# ---- diff ------------------------------------------------------------


def compute_diff(env: "Environment", module: str) -> Diff:
    """Diff the live DB schema against the models owned by ``module``.

    Only models registered as owned by the module (via the loader's
    ``registry._model_module`` map) are considered — inherited
    extensions are the originating module's responsibility.
    """
    diff = Diff()
    reg = env.registry
    owned = sorted(
        name for name, owner in reg._model_module.items() if owner == module
    )
    for model_name in owned:
        cls = reg[model_name]
        table = cls._table
        expected: dict[str, str] = {}
        for f in cls._fields.values():
            if not f.is_stored:
                continue
            if isinstance(f, (One2many, Many2many)):
                continue
            expected[f.column] = f.column_ddl()
        actual = _existing_columns(env, table)
        if actual is None:
            # Table missing entirely — emit CREATE TABLE with all
            # currently-declared columns. Mirrors `_setup_table`.
            col_ddls = ['"id" SERIAL PRIMARY KEY'] + list(expected.values())
            ddl = (
                f'CREATE TABLE IF NOT EXISTS "{table}" '
                f'({", ".join(col_ddls)})'
            )
            diff.new_tables.append((table, ddl))
            continue
        for col, col_ddl in expected.items():
            if col in actual:
                continue
            # Strip trailing NOT NULL — adding NOT NULL columns to a
            # populated table fails without a DEFAULT. The TODO comment
            # rendered below reminds the operator to backfill + tighten.
            field_obj = next(
                (f for f in cls._fields.values()
                 if f.is_stored and f.column == col),
                None,
            )
            was_required = bool(field_obj and getattr(field_obj, "required", False))
            safe_ddl = col_ddl.rstrip()
            if safe_ddl.upper().endswith("NOT NULL"):
                safe_ddl = safe_ddl[: -len("NOT NULL")].rstrip()
            stmt = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {safe_ddl}'
            diff.new_columns.append((table, col, stmt, was_required))
        for col in actual:
            if col == "id":
                continue
            if col not in expected:
                diff.orphan_columns.append((table, col))
    return diff


def _existing_columns(env, table: str) -> set[str] | None:
    """Return the set of column names for ``table``, or None if the
    table doesn't exist at all (distinguishes "no rows" from "no
    table" — both look the same on the columns query)."""
    rows = env.conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = %s",
        (table,),
    ).fetchall()
    if rows:
        return {r[0] for r in rows}
    exists = env.conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        (table,),
    ).fetchone()
    return set() if exists else None


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
    out.append("Drops are commented out — uncomment after reviewing.")
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
    if diff.orphan_columns:
        parts.append(f"{len(diff.orphan_columns)} orphan column(s)")
    return "Changes: " + ", ".join(parts) + "."


def _q(s: str) -> str:
    """Emit a Python single-quoted string literal. SQL identifiers /
    keywords are ASCII so we don't worry about non-printables."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    # Last resort: escape single quotes.
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---- version helpers -------------------------------------------------


def next_minor_version(version: tuple[int, ...]) -> tuple[int, ...]:
    """``(0, 16, 0) → (0, 17, 0)``; ``(0, 16) → (0, 17)``.

    Pads with zeros if shorter than (major, minor); otherwise just
    increments the minor component in place.
    """
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
    """``(0, 16) → (0, 17)`` ↦ ``"0_16_to_0_17.py"``.

    Trailing zeros are dropped to match the project convention
    (``0_15_to_0_16.py``, not ``0_15_0_to_0_16_0.py``).
    """
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
    """Outcome of applying a schema diff in-process (no migration file)."""

    new_tables: int = 0
    new_columns: int = 0

    @property
    def is_empty(self) -> bool:
        return self.new_tables == 0 and self.new_columns == 0

    def summary(self) -> str:
        if self.is_empty:
            return "schema unchanged"
        parts: list[str] = []
        if self.new_tables:
            parts.append(f"{self.new_tables} table(s)")
        if self.new_columns:
            parts.append(f"{self.new_columns} column(s)")
        return "schema: " + ", ".join(parts)


def apply_schema_diff(env: "Environment", module: str) -> ApplyResult:
    """Apply additive DDL from ``compute_diff`` immediately.

    Used on Apps **Upgrade / Sync** so operators need not hand-run
    ``pyvelm db autogen`` for every column addition. Idempotent
    (``IF NOT EXISTS``). Does not write a migration file.
    """
    diff = compute_diff(env, module)
    result = ApplyResult(
        new_tables=len(diff.new_tables),
        new_columns=len(diff.new_columns),
    )
    if diff.is_empty:
        return result
    for _, ddl in diff.new_tables:
        env.conn.execute(ddl)
    for _table, _col, stmt, _was_required in diff.new_columns:
        env.conn.execute(stmt)
    return result
