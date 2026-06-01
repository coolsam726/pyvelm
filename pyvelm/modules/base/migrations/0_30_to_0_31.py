"""Add menu_layout on res.company."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _alter(t):
        t.string("menu_layout", nullable=True)

    schema.table("res_company", _alter)
    schema.update_rows("res_company", {"menu_layout": ""}, menu_layout=None)
