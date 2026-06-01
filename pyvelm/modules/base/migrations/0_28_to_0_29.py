"""Drive-style folders on ir.attachment."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("ir_attachment", lambda t: t.integer("folder_id", nullable=True))
