"""Migration 0.20.0 → 0.21.0 — dark-mode logo URL on ``res_company``."""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "logo_url_dark" text'
    )
