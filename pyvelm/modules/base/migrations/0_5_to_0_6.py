"""Add multi-company support: res_company and company_id FKs."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _company(t):
        t.string("name", nullable=False)
        t.boolean("active", nullable=True)

    schema.create("res_company", _company)

    def _users(t):
        t.foreign_id("company_id", "res_company", ondelete="SET NULL", nullable=True)

    schema.table("res_users", _users)

    def _partner(t):
        t.foreign_id("company_id", "res_company", ondelete="SET NULL", nullable=True)

    schema.table("res_partner", _partner)
