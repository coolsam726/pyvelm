"""Module rename report_layout → document_layout."""

from document_layout.hooks import _migrate_company_field
from pyvelm.migrations import Blueprint, Schema


def upgrade(env):
    schema = Schema(env)
    schema.rename_module("report_layout", "document_layout")
    _migrate_company_field(env)
