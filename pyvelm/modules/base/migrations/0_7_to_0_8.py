"""Introduce the `ir.ui.menu` model.

The sidebar in 0.7.0 was hard-coded inside the renderer. 0.8.0 moves
navigation into a data model so each module contributes its own entries
via a `MENUS` data file, mirroring how `ir.ui.view` handles views.

Fresh installs get the table via `_setup_module_schema`. Upgraded
installs need it created here so the `_sync_menus` pass at the end of
the install cycle has somewhere to write to.

Idempotent: every DDL uses `IF NOT EXISTS`.
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'CREATE TABLE IF NOT EXISTS "ir_ui_menu" ('
        '"id" SERIAL PRIMARY KEY, '
        '"module" text NOT NULL, '
        '"name" text NOT NULL, '
        '"label" text NOT NULL, '
        '"parent_id" integer, '
        '"sequence" integer DEFAULT 10, '
        '"href" text, '
        '"icon" text, '
        '"active" boolean DEFAULT TRUE)'
    )
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_menu" '
        'DROP CONSTRAINT IF EXISTS "ir_ui_menu_parent_id_fkey"'
    )
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_menu" '
        'ADD CONSTRAINT "ir_ui_menu_parent_id_fkey" '
        'FOREIGN KEY ("parent_id") REFERENCES "ir_ui_menu"("id") '
        'ON DELETE CASCADE'
    )
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_menu" '
        'ADD COLUMN IF NOT EXISTS "access_model" text'
    )
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_menu" '
        'ADD COLUMN IF NOT EXISTS "access_perm" text'
    )
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_menu" '
        'ADD COLUMN IF NOT EXISTS "access_policy" text'
    )
