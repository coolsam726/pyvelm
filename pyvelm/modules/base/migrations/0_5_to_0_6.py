"""Migration 0.5.0 → 0.6.0: add multi-company support.

Creates the res_company table and adds company_id columns to
res_users and res_partner. All DDL uses IF NOT EXISTS / ADD COLUMN IF
NOT EXISTS so running on a fresh install is noise-free.
"""


def migrate(env):
    conn = env.conn

    # ---- res.company ----
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "res_company" (
            "id"     SERIAL PRIMARY KEY,
            "name"   text NOT NULL,
            "active" boolean
        )
    ''')

    # ---- company_id FK on res_users ----
    conn.execute('''
        ALTER TABLE "res_users"
        ADD COLUMN IF NOT EXISTS "company_id"
            integer REFERENCES "res_company"("id") ON DELETE SET NULL
    ''')

    # ---- company_id FK on res_partner ----
    conn.execute('''
        ALTER TABLE "res_partner"
        ADD COLUMN IF NOT EXISTS "company_id"
            integer REFERENCES "res_company"("id") ON DELETE SET NULL
    ''')
