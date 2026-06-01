"""Add ir_cron.lastcall column."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("ir_cron", lambda t: t.timestamp("lastcall", nullable=True))
