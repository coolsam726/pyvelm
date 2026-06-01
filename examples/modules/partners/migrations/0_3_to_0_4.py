"""Add birth_date to res.partner for the date picker demo."""

from pyvelm.migrations import Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.date("birth_date", nullable=True)

    schema.table("res_partner", _alter)
