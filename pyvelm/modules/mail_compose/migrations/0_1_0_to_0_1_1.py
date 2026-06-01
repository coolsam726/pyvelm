"""Relax NOT NULL on mail_compose_message.recipient_to."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "mail_compose_message", lambda t: t.allow_null("recipient_to")
    )
