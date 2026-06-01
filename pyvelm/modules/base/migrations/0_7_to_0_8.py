"""Introduce the ir.ui.menu model."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _menu(t: Table) -> None:
        t.string("module", nullable=False)
        t.string("name", nullable=False)
        t.string("label", nullable=False)
        t.integer("parent_id", nullable=True)
        t.integer("sequence", nullable=True).default(10)
        t.string("href")
        t.string("icon")
        t.boolean("active", nullable=True).default(True)

    schema.create("ir_ui_menu", _menu)

    def _alter(t: Table) -> None:
        t.drop_constraint("ir_ui_menu_parent_id_fkey")
        t.foreign_key(
            "parent_id",
            "ir_ui_menu",
            ondelete="CASCADE",
            name="ir_ui_menu_parent_id_fkey",
        )
        t.string("access_model")
        t.string("access_perm")
        t.string("access_policy")

    schema.table("ir_ui_menu", _alter)
