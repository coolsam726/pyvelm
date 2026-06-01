"""Migration 0.19.0 → 0.20.0 — white-label branding columns on ``res_company``."""




from pyvelm.database import execute_migration_sql

def migrate(env):
    cols = [
        ("app_name", "text"),
        ("app_tagline", "text"),
        ("logo_url", "text"),
        ("favicon_url", "text"),
        ("copyright_text", "text"),
        ("support_email", "text"),
        ("support_url", "text"),
        ("show_powered_by", "boolean DEFAULT true"),
    ]
    for name, ddl in cols:
        execute_migration_sql(env.conn, 
            f'ALTER TABLE "res_company" ADD COLUMN IF NOT EXISTS "{name}" {ddl}'
        )
