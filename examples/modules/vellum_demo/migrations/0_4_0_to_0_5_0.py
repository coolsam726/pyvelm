"""Add ``snippet`` (Code field) on vellum.demo.note."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "vellum_demo_note" '
        'ADD COLUMN IF NOT EXISTS "snippet" text'
    )
