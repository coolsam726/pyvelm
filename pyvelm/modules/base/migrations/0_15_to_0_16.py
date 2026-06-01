"""Rename ECB rate fetcher cron/action to Currency Rate Sync from ECB."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.update_rows(
        "ir_cron",
        {"name": "Currency Rate Sync from ECB"},
        name="ECB rate fetcher",
    )
    schema.update_rows(
        "ir_actions_server",
        {"name": "Currency Rate Sync from ECB"},
        name="ECB rate fetcher",
    )
