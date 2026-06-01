"""Migration 0.1.0 → 0.2.0 — approval deadlines + escalation cron."""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "workflow_approval" '
        'ADD COLUMN IF NOT EXISTS "deadline_at" timestamp'
    )
