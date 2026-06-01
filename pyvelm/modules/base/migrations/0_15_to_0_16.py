"""Rename "ECB rate fetcher" → "Currency Rate Sync from ECB".

The bundled ECB rate-fetcher server action + cron were originally
seeded under the developer-y name "ECB rate fetcher". A more
descriptive label fits the admin UI better.

Idempotent: matches the old name only — re-running this migration
or running it after a fresh install (which already seeds the new
name) is a no-op.
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'UPDATE "ir_cron" SET "name" = %s WHERE "name" = %s',
        ("Currency Rate Sync from ECB", "ECB rate fetcher"),
    )
    execute_migration_sql(env.conn, 
        'UPDATE "ir_actions_server" SET "name" = %s WHERE "name" = %s',
        ("Currency Rate Sync from ECB", "ECB rate fetcher"),
    )
