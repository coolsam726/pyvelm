"""Configurable document header logo height."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.table(
        "res_company",
        lambda t: t.integer("document_logo_height", nullable=True).default(0),
    )
    schema.update_rows(
        "res_company", {"document_logo_height": 0}, document_logo_height=None
    )
