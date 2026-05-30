"""Install/sync hooks for document_layout."""
from __future__ import annotations


def install(env):
    _migrate_company_field(env)
    _seed_defaults(env)


def sync(env):
    _adopt_legacy_module(env)
    _migrate_company_field(env)
    _seed_defaults(env)


def _adopt_legacy_module(env) -> None:
    """Rename ``ir_module`` row ``report_layout`` → ``document_layout`` when upgrading."""
    cur = env.conn.execute(
        'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("report_layout",),
    ).fetchone()
    if not cur:
        return
    newer = env.conn.execute(
        'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("document_layout",),
    ).fetchone()
    if newer:
        env.conn.execute('DELETE FROM "ir_module" WHERE "name" = %s', ("report_layout",))
    else:
        env.conn.execute(
            'UPDATE "ir_module" SET "name" = %s WHERE "name" = %s',
            ("document_layout", "report_layout"),
        )


def _migrate_company_field(env) -> None:
    """Move data from legacy ``report_layout`` column to ``document_layout``."""
    from pyvelm.database import column_exists

    conn = env.conn
    cols: set[str] = set()
    for name in ("report_layout", "document_layout"):
        if column_exists(conn, "res_company", name):
            cols.add(name)
    if "report_layout" in cols and "document_layout" in cols:
        conn.execute(
            'UPDATE "res_company" SET "document_layout" = "report_layout" '
            'WHERE ("document_layout" IS NULL OR "document_layout" = \'\') '
            'AND "report_layout" IS NOT NULL AND "report_layout" != \'\'',
        )
        conn.execute('ALTER TABLE "res_company" DROP COLUMN IF EXISTS "report_layout"')
    elif "report_layout" in cols:
        conn.execute(
            'ALTER TABLE "res_company" RENAME COLUMN "report_layout" TO "document_layout"',
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
