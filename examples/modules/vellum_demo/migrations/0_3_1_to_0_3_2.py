"""Add ``created_at`` / ``updated_at`` to Vellum demo tables."""


def migrate(env):
    for table in (
        "vellum_demo_note",
        "vellum_demo_comment",
        "vellum_demo_soft_note",
    ):
        env.conn.execute(
            f'ALTER TABLE "{table}" '
            f'ADD COLUMN IF NOT EXISTS "created_at" timestamp'
        )
        env.conn.execute(
            f'ALTER TABLE "{table}" '
            f'ADD COLUMN IF NOT EXISTS "updated_at" timestamp'
        )
