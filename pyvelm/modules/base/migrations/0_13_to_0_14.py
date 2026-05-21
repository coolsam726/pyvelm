"""Add ir_cron.lastcall column.

Records the timestamp of each job's most recent execution (set by
``CronJob.run_due`` and by the on-demand ``CronJob.run_now``). The
admin list view displays it next to ``nextcall`` so operators can
confirm at a glance that a job is actually firing.

Idempotent: ``ADD COLUMN IF NOT EXISTS``. Existing rows stay NULL
until their next run.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "ir_cron" '
        'ADD COLUMN IF NOT EXISTS "lastcall" timestamp'
    )
