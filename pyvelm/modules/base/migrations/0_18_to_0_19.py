"""Migration 0.18.0 → 0.19.0 — add ``res_company.primary_color``.

Stores a hex accent (e.g. ``#6366f1``) used to override the default
primary palette for users scoped to that company.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "primary_color" text'
    )
