"""Approval deadlines + escalation cron."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "workflow_approval", lambda t: t.timestamp("deadline_at", nullable=True)
    )
