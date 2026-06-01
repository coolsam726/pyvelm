"""Add session_token column to res_users."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("res_users", lambda t: t.string("session_token", nullable=True))
