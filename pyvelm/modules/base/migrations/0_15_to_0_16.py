"""Rename "ECB rate fetcher" → "Currency Rate Sync from ECB".

The bundled ECB rate-fetcher server action + cron were originally
seeded under the developer-y name "ECB rate fetcher". A more
descriptive label fits the admin UI better.

Idempotent: matches the old name only — re-running this migration
or running it after a fresh install (which already seeds the new
name) is a no-op.
"""


def migrate(env):
    env.conn.execute(
        'UPDATE "ir_cron" SET "name" = %s WHERE "name" = %s',
        ("Currency Rate Sync from ECB", "ECB rate fetcher"),
    )
    env.conn.execute(
        'UPDATE "ir_actions_server" SET "name" = %s WHERE "name" = %s',
        ("Currency Rate Sync from ECB", "ECB rate fetcher"),
    )
