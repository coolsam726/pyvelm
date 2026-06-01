"""Migration 0.1.0 → 0.2.0 — module rename ``report_layout`` → ``document_layout``."""



from pyvelm.database import execute_migration_sql, fetchone_migration

from document_layout.hooks import _migrate_company_field


def migrate(env):
    conn = env.conn
    has_old = fetchone_migration(conn, 'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("report_layout",),)
    has_new = fetchone_migration(conn, 'SELECT 1 FROM "ir_module" WHERE "name" = %s', ("document_layout",),)
    if has_old and not has_new:
        execute_migration_sql(conn, 
            'UPDATE "ir_module" SET "name" = %s WHERE "name" = %s',
            ("document_layout", "report_layout"),
        )
    elif has_old and has_new:
        execute_migration_sql(conn, 'DELETE FROM "ir_module" WHERE "name" = %s', ("report_layout",))
    _migrate_company_field(env)
