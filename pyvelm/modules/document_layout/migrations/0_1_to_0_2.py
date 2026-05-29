"""Migration 0.1.0 → 0.2.0 — module rename ``report_layout`` → ``document_layout``."""

from document_layout.hooks import _migrate_company_field


def migrate(env):
    conn = env.conn
    has_old = conn.execute(
        'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("report_layout",),
    ).fetchone()
    has_new = conn.execute(
        'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("document_layout",),
    ).fetchone()
    if has_old and not has_new:
        conn.execute(
            'UPDATE "ir_module" SET "name" = %s WHERE "name" = %s',
            ("document_layout", "report_layout"),
        )
    elif has_old and has_new:
        conn.execute('DELETE FROM "ir_module" WHERE "name" = %s', ("report_layout",))
    _migrate_company_field(env)
