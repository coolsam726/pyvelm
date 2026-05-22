"""Add ``vellum.demo.soft_note`` and ``deleted_at`` for soft-delete tests."""


def migrate(env):
    Soft = env["vellum.demo.soft_note"]
    Soft._setup_table(env.conn)
    env.conn.execute(
        'ALTER TABLE "vellum_demo_soft_note" '
        'ADD COLUMN IF NOT EXISTS "deleted_at" timestamp'
    )
