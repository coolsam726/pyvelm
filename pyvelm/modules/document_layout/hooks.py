from __future__ import annotations

from pyvelm.migrations import Schema


def install(env):
    _migrate_company_field(env)
    _seed_defaults(env)


def sync(env):
    _adopt_legacy_module(env)
    _migrate_company_field(env)
    _seed_defaults(env)


def _adopt_legacy_module(env) -> None:
    """Rename ir_module row report_layout → document_layout when upgrading."""
    Schema(env).rename_module("report_layout", "document_layout")


def _migrate_company_field(env) -> None:
    """Move data from legacy report_layout column to document_layout."""
    from pyvelm.database import column_exists

    schema = Schema(env)
    conn = env.conn
    has_old = column_exists(conn, "res_company", "report_layout")
    has_new = column_exists(conn, "res_company", "document_layout")
    if has_old and has_new:
        schema.copy_column_if_dest_empty(
            "res_company", "document_layout", "report_layout"
        )
        schema.table("res_company", lambda t: t.drop_column("report_layout"))
    elif has_old:
        schema.table(
            "res_company",
            lambda t: t.rename_column("report_layout", "document_layout"),
        )


def _seed_defaults(env) -> None:
    """Default document_layout / paper_format on companies that have none."""
    if "res.company" not in env.registry:
        return
    for company in env["res.company"].search([]):
        vals = {}
        if not company.document_layout:
            vals["document_layout"] = "light"
        if not company.paper_format:
            vals["paper_format"] = "A4"
        if vals:
            company.write(vals)
