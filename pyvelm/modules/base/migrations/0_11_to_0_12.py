"""Rename res_currency_rate.name → res_currency_rate.date.

Previously the rate's effective-from timestamp lived in the ``name``
column. ``name`` is now a computed display label (``"<code> @
<date>"``) so the storage column is renamed to make its purpose
obvious.

Idempotent:
  - ``ADD COLUMN IF NOT EXISTS`` for the new column
  - copy old → new only when the old column is still present
  - drop the old column only after the copy succeeds
"""

from pyvelm.database import execute_migration_sql, fetchone_migration


def migrate(env):
    conn = env.conn

    execute_migration_sql(
        conn,
        'ALTER TABLE "res_currency_rate" '
        'ADD COLUMN IF NOT EXISTS "date" timestamp',
    )

    row = fetchone_migration(
        conn,
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'res_currency_rate' AND column_name = 'name'",
    )
    if row:
        execute_migration_sql(
            conn,
            'UPDATE "res_currency_rate" '
            'SET "date" = "name" WHERE "date" IS NULL',
        )
        execute_migration_sql(
            conn,
            'ALTER TABLE "res_currency_rate" DROP COLUMN IF EXISTS "name"',
        )
