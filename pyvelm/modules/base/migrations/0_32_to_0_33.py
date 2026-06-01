"""Migration 0.32.0 → 0.33.0 — header logo height + show brand text in chrome."""



from pyvelm.database import execute_migration_sql

from __future__ import annotations


def migrate(env):
    conn = env.conn
    execute_migration_sql(conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "header_logo_height" integer DEFAULT 0'
    )
    execute_migration_sql(conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "show_header_brand_text" boolean DEFAULT true'
    )
    execute_migration_sql(conn, 
        'UPDATE "res_company" SET "header_logo_height" = 0 '
        'WHERE "header_logo_height" IS NULL'
    )
    execute_migration_sql(conn, 
        'UPDATE "res_company" SET "show_header_brand_text" = true '
        'WHERE "show_header_brand_text" IS NULL'
    )
