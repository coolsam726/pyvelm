"""Migration 0.30.0 → 0.31.0 — per-company navigation layout on ``res.company``.

Adds the nullable ``menu_layout`` column. Fresh installs get it through
``_setup_table``; this ``ALTER`` is the safety net for databases that update
base before re-syncing schema.
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "menu_layout" VARCHAR NULL'
    )
    execute_migration_sql(env.conn, 
        'UPDATE "res_company" SET "menu_layout" = \'\' '
        'WHERE "menu_layout" IS NULL'
    )
