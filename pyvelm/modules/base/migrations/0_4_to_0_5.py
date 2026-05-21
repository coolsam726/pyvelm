"""Add Stage 6 tables: ir_actions_server, base_automation,
ir_cron, mail_message.

All use CREATE TABLE IF NOT EXISTS so this is safe to run on a
fresh install (where the model's _setup_table already ran) as well
as on a real 0.4.x -> 0.5.0 upgrade.
"""


def migrate(env):
    conn = env.conn

    # ---- ir.actions.server ----
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "ir_actions_server" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "model" text NOT NULL,
            "action_type" text NOT NULL,
            "vals_json" text,
            "code" text
        )
    ''')

    # ---- base.automation ----
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "base_automation" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "model" text NOT NULL,
            "trigger" text NOT NULL,
            "action_id" integer REFERENCES "ir_actions_server"("id") ON DELETE CASCADE,
            "active" boolean
        )
    ''')

    # ---- ir.cron ----
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "ir_cron" (
            "id" SERIAL PRIMARY KEY,
            "name" text NOT NULL,
            "action_id" integer REFERENCES "ir_actions_server"("id") ON DELETE CASCADE,
            "interval_number" integer,
            "interval_type" text,
            "nextcall" timestamp,
            "active" boolean
        )
    ''')

    # ---- mail.message ----
    conn.execute('''
        CREATE TABLE IF NOT EXISTS "mail_message" (
            "id" SERIAL PRIMARY KEY,
            "model" text,
            "res_id" integer,
            "author_id" integer REFERENCES "res_users"("id") ON DELETE SET NULL,
            "body" text,
            "message_type" text,
            "subtype" text,
            "date" timestamp
        )
    ''')
