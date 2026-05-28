"""Migration 0.28.0 → 0.29.0 — Drive-style folders on ``ir.attachment``.

The new ``folder_id`` column on ``ir.attachment`` is added by the
``file_manager`` module's ``_inherit``, and schema autogen handles
this on fresh installs. The explicit ``ALTER TABLE`` here is a
belt-and-braces safety net for databases that update base before
re-installing file_manager (the autogen path only runs when
file_manager itself is being installed / synced).

No data backfill — every existing attachment stays valid in the new
"Unfiled" bucket (``folder_id IS NULL``).
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "ir_attachment" '
        'ADD COLUMN IF NOT EXISTS "folder_id" INTEGER NULL'
    )
