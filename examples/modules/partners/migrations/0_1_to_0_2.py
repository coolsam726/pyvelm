"""Add Partner.code; backfill via partners.hooks sync."""

from pyvelm.migrations import Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.string("code", nullable=True)

    schema.table("res_partner", _alter)
