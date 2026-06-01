"""Ensure deleted_at exists on vellum_demo_soft_note."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "vellum_demo_soft_note", lambda t: t.timestamp("deleted_at", nullable=True)
    )
