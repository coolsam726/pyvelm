"""Migration 0.19.0 → 0.20.0 — white-label branding columns on ``res_company``."""


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
        env.conn.execute(
            f'ALTER TABLE "res_company" ADD COLUMN IF NOT EXISTS "{name}" {ddl}'
        )
