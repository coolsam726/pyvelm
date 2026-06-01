"""Add view inheritance columns to ir.ui.view.

The 0.1.0 schema only had (module, name, model, view_type, arch).
Inheritance adds priority/inherit_id/operations and relaxes arch to be
nullable (extension views don't carry their own arch).
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 'ALTER TABLE "ir_ui_view" ALTER COLUMN "arch" DROP NOT NULL')
    execute_migration_sql(env.conn, 'ALTER TABLE "ir_ui_view" ADD COLUMN IF NOT EXISTS "priority" integer NOT NULL DEFAULT 16')
    execute_migration_sql(env.conn, 'ALTER TABLE "ir_ui_view" ADD COLUMN IF NOT EXISTS "inherit_id" integer')
    execute_migration_sql(env.conn, 'ALTER TABLE "ir_ui_view" ADD COLUMN IF NOT EXISTS "operations" text')
    execute_migration_sql(env.conn, 
        'ALTER TABLE "ir_ui_view" '
        'ADD CONSTRAINT "ir_ui_view_inherit_id_fkey" '
        'FOREIGN KEY ("inherit_id") REFERENCES "ir_ui_view"("id") '
        'ON DELETE CASCADE'
    )
