"""Add session_token column to res_users (Slice B: session login)."""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, """
        ALTER TABLE "res_users"
        ADD COLUMN IF NOT EXISTS "session_token" text
    """)
