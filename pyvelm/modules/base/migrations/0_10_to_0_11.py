"""Add `currency_id` to res.company; backfill existing rows with USD.

Slice B of Stage 11. Each company now has a "home" currency that
Monetary fields (slice C) read by default. Existing companies on
upgraded databases get USD as a sensible neutral default — operators
can change it from Settings → Companies.

Idempotent: ADD COLUMN IF NOT EXISTS, and the backfill only touches
rows where currency_id is NULL.
"""


def migrate(env):
    conn = env.conn

    conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "currency_id" '
        'integer REFERENCES "res_currency"("id") ON DELETE SET NULL'
    )

    # Backfill existing companies with USD if a USD row exists.
    # The 0_9_to_0_10 migration (or the install hook) seeds it, so
    # by the time this runs there should be one — but we defensively
    # tolerate the absence rather than crash mid-upgrade.
    row = conn.execute(
        'SELECT "id" FROM "res_currency" WHERE "code" = %s LIMIT 1',
        ("USD",),
    ).fetchone()
    if row:
        usd_id = row[0]
        conn.execute(
            'UPDATE "res_company" SET "currency_id" = %s '
            'WHERE "currency_id" IS NULL',
            (usd_id,),
        )
