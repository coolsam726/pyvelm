"""Add res_company.font_family."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("res_company", lambda t: t.string("font_family", nullable=True))
    schema.update_rows("res_company", {"font_family": ""}, font_family=None)
