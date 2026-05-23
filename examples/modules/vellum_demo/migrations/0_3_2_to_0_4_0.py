"""Add date / datetime / time demo columns on vellum.demo.note."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "vellum_demo_note" '
        'ADD COLUMN IF NOT EXISTS "publish_on" date'
    )
    env.conn.execute(
        'ALTER TABLE "vellum_demo_note" '
        'ADD COLUMN IF NOT EXISTS "event_at" timestamp'
    )
    env.conn.execute(
        'ALTER TABLE "vellum_demo_note" '
        'ADD COLUMN IF NOT EXISTS "standup_at" time'
    )
