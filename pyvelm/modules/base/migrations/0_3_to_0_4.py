"""Add session_token column to res_users (Slice B: session login)."""


def migrate(env):
    env.conn.execute("""
        ALTER TABLE "res_users"
        ADD COLUMN IF NOT EXISTS "session_token" text
    """)
