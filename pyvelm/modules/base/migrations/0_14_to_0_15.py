"""Add res_company.timezone column."""

from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "res_company",
        lambda t: t.string("timezone", nullable=True).default("UTC"),
    )
