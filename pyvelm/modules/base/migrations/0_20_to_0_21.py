"""Migration 0.20.0 → 0.21.0 — dark-mode logo URL on ``res_company``."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "logo_url_dark" text'
    )
