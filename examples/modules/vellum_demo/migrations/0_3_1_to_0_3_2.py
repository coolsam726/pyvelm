"""Add created_at / updated_at to Vellum demo tables."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _timestamps(t: Table) -> None:
        t.timestamp("created_at", nullable=True)
        t.timestamp("updated_at", nullable=True)

    for table in (
        "vellum_demo_note",
        "vellum_demo_comment",
        "vellum_demo_soft_note",
    ):
        schema.table(table, _timestamps)
