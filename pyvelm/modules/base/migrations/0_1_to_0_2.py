"""Add view inheritance columns to ir.ui.view."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.drop_nullable("arch")
        t.integer("priority", nullable=False).default(16)
        t.integer("inherit_id", nullable=True)
        t.text("operations", nullable=True)
        t.foreign_key(
            "inherit_id",
            "ir_ui_view",
            ondelete="CASCADE",
            name="ir_ui_view_inherit_id_fkey",
        )

    schema.table("ir_ui_view", _alter)
