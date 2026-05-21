"""Add ACL schema: res.groups, res.users, ir.model.access, ir.rule.

Defensive ADD COLUMN / CREATE TABLE IF NOT EXISTS — fresh installs at
0.3.0 already get these from the model classes, so the migration is
only effective on a real 0.2.0 -> 0.3.0 upgrade.

On real upgrades, no seed data is created here; the existing install
state is preserved and the operator is expected to create their first
admin user via their own seed script. The base install hook only
runs on the *first* install (current is None), not on upgrades.
"""


def migrate(env):
    conn = env.conn
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "res_groups" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "res_users" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "login" text NOT NULL,
            "password" text,
            "active" boolean
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "res_groups_res_users_rel" (
            "res_groups_id" integer NOT NULL REFERENCES "res_groups"("id") ON DELETE CASCADE,
            "res_users_id" integer NOT NULL REFERENCES "res_users"("id") ON DELETE CASCADE,
            PRIMARY KEY ("res_groups_id", "res_users_id")
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "ir_model_access" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "model" text NOT NULL,
            "group_id" integer REFERENCES "res_groups"("id") ON DELETE SET NULL,
            "perm_read" boolean,
            "perm_write" boolean,
            "perm_create" boolean,
            "perm_unlink" boolean
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "ir_rule" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "model" text NOT NULL,
            "group_id" integer REFERENCES "res_groups"("id") ON DELETE SET NULL,
            "perm_read" boolean,
            "perm_write" boolean,
            "perm_create" boolean,
            "perm_unlink" boolean,
            "domain" text NOT NULL
        )
    ''')
