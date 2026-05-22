"""Ensure ``deleted_at`` exists on ``vellum_demo_soft_note``."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "vellum_demo_soft_note" '
        'ADD COLUMN IF NOT EXISTS "deleted_at" timestamp'
    )
