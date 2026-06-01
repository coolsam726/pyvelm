"""Migration 0.18.0 → 0.19.0 — add ``res_company.primary_color``.

Stores a hex accent (e.g. ``#6366f1``) used to override the default
primary palette for users scoped to that company.
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "primary_color" text'
    )
