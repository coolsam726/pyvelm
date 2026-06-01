"""Add res_company.timezone column.

Companies now carry an IANA timezone (e.g. ``Africa/Nairobi``). The
render layer uses this to localize Datetime widgets — UTC stays in
the DB, conversion happens at the boundaries.

Idempotent: ``ADD COLUMN IF NOT EXISTS``. Existing companies default
to ``"UTC"`` so behavior is unchanged until an operator sets a real
timezone.
"""




from pyvelm.database import execute_migration_sql

def migrate(env):
    execute_migration_sql(env.conn, 
        'ALTER TABLE "res_company" '
        "ADD COLUMN IF NOT EXISTS \"timezone\" text DEFAULT 'UTC'"
    )
