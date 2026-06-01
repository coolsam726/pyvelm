"""Outgoing-mail dispatcher columns + seed dispatcher cron."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.string("recipient_email", nullable=True)
        t.string("subject", nullable=True)
        t.string("state", nullable=True).default("outgoing")
        t.string("error", nullable=True)

    schema.table("mail_message", _alter)

    from base import hooks

    hooks._seed_mail_dispatcher(env)
