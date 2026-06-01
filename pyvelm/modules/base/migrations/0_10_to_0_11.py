"""Add currency_id to res.company; backfill with USD when present."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _alter(t):
        t.foreign_id(
            "currency_id", "res_currency", ondelete="SET NULL", nullable=True
        )

    schema.table("res_company", _alter)

    row = schema._fetchone("res_currency", {"code": "USD"})
    if row:
        schema.update_rows(
            "res_company", {"currency_id": row[0]}, currency_id=None
        )
