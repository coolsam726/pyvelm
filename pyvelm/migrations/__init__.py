"""Laravel-style declarative schema migrations (SQLAlchemy Core, all backends).

Type the builder callback for IDE autocomplete::

    from pyvelm.migrations import Schema, Table

    def _alter(t: Table) -> None:
        t.string("name", nullable=False)
"""
from __future__ import annotations

from .schema import (
    SUPPORTED_ALTERATIONS,
    SUPPORTED_COLUMN_BUILDERS,
    Blueprint,
    Schema,
    Table,
    TableCallback,
)

__all__ = [
    "Blueprint",
    "Schema",
    "Table",
    "TableCallback",
    "SUPPORTED_COLUMN_BUILDERS",
    "SUPPORTED_ALTERATIONS",
]
