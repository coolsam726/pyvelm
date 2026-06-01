"""Rename res_currency_rate.name to res_currency_rate.date."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _add_date(t):
        t.timestamp("date", nullable=True)

    schema.table("res_currency_rate", _add_date)

    if schema.has_column("res_currency_rate", "name"):
        schema.copy_column("res_currency_rate", "date", "name")
        schema.table("res_currency_rate", lambda t: t.drop_column("name"))
