"""Add res.users.avatar_url."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("res_users", lambda t: t.string("avatar_url", nullable=True))
