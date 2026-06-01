"""Add vellum.demo.soft_note and deleted_at for soft-delete tests."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    env["vellum.demo.soft_note"]._setup_table(env.conn)
    schema = Schema(env)
    schema.table(
        "vellum_demo_soft_note", lambda t: t.timestamp("deleted_at", nullable=True)
    )
