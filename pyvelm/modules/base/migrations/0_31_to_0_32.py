"""Migration 0.31.0 → 0.32.0 — add ``res_company.font_family``."""



from pyvelm.database import execute_migration_sql

from __future__ import annotations


def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "font_family" text'
    )
    execute_migration_sql(env.conn, 
        'UPDATE "res_company" SET "font_family" = \'\' '
        'WHERE "font_family" IS NULL'
    )
