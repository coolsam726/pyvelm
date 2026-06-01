"""Add sequence column to res.tag for drag-reorder support."""

from pyvelm.migrations import Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.integer("sequence", nullable=True).default(10)

    schema.table("res_tag", _alter)
    if "res.tag" not in env.registry:
        return
    Tag = env["res.tag"]
    for tag in Tag.search([]):
        if tag.sequence is None or tag.sequence == 10:
            tag.sequence = tag.id * 10
