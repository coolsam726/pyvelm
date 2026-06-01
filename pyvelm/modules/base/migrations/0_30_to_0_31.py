"""Add menu_layout on res.company."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.string("menu_layout", nullable=True)

    schema.table("res_company", _alter)
    schema.update_rows("res_company", {"menu_layout": ""}, menu_layout=None)
