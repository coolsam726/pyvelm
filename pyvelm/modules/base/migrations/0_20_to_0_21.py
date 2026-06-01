"""Add res_company.logo_url_dark."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("res_company", lambda t: t.string("logo_url_dark", nullable=True))
