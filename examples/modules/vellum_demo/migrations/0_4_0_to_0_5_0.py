"""Add snippet (Code field) on vellum.demo.note."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("vellum_demo_note", lambda t: t.text("snippet", nullable=True))
