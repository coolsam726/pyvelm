"""Migration 0.30.0 → 0.31.0 — per-company navigation layout on ``res.company``.

Adds the nullable ``menu_layout`` column. Fresh installs get it through
``_setup_table``; this ``ALTER`` is the safety net for databases that update
base before re-syncing schema.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "menu_layout" VARCHAR NULL'
    )
    env.conn.execute(
        'UPDATE "res_company" SET "menu_layout" = \'\' '
        'WHERE "menu_layout" IS NULL'
    )
