"""Add `sequence` column to res.tag for drag-reorder support.

The field is declared in the 0.3.0 model definition; fresh installs
pick it up via `_setup_table`. Upgraded installs need the column
added explicitly + a backfill so existing rows aren't NULL on a
NOT NULL-defaulted column.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_tag" '
        'ADD COLUMN IF NOT EXISTS "sequence" INTEGER DEFAULT 10'
    )
    # Backfill so already-seeded tags get a sequence that mirrors their
    # creation order. New tags from this point forward use the default.
    env.conn.execute(
        'UPDATE "res_tag" SET "sequence" = "id" * 10 '
        'WHERE "sequence" IS NULL OR "sequence" = 10'
    )
