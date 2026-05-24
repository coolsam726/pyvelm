"""Migration 0.1.0 → 0.2.0 — approval deadlines + escalation cron."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "workflow_approval" '
        'ADD COLUMN IF NOT EXISTS "deadline_at" timestamp'
    )
