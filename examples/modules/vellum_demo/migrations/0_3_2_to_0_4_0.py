"""Add date / datetime / time demo columns on vellum.demo.note."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.date("publish_on", nullable=True)
        t.timestamp("event_at", nullable=True)
        t.time("standup_at", nullable=True)

    schema.table("vellum_demo_note", _alter)
