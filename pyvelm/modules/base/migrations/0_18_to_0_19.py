"""Add res_company.primary_color."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table("res_company", lambda t: t.string("primary_color", nullable=True))
