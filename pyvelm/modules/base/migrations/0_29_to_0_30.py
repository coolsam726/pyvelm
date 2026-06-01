"""Company stamp on ir.attachment."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "ir_attachment",
        lambda t: t.foreign_id("company_id", "res_company", ondelete="SET NULL"),
    )
