"""Add res.currency + res.currency.rate; seed currencies."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _currency(t):
        t.string("code", nullable=False)
        t.string("name", nullable=True)
        t.string("symbol", nullable=True).default("$")
        t.float("rounding", nullable=True).default(0.01)
        t.boolean("active", nullable=True).default(True)

    schema.create("res_currency", _currency)

    def _rate(t):
        t.foreign_id("currency_id", "res_currency", ondelete="CASCADE", nullable=False)
        t.timestamp("name", nullable=True)
        t.float("rate", nullable=True).default(1.0)

    schema.create("res_currency_rate", _rate)

    def _fk(t):
        t.drop_constraint("res_currency_rate_currency_id_fkey")
        t.foreign_key(
            "currency_id",
            "res_currency",
            ondelete="CASCADE",
            name="res_currency_rate_currency_id_fkey",
        )

    schema.table("res_currency_rate", _fk)

    from base import hooks

    hooks._seed_currencies(env)
