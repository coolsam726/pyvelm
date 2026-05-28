"""Add `Partner.code` and backfill from name + id.

Idempotent backfill lives in ``partners.hooks:sync`` (``SYNC_HOOK``) so
Apps Sync and ``db migrate`` at the same version still fill NULLs before
``SET NOT NULL``. This migration runs once on version bump only.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_partner" ADD COLUMN IF NOT EXISTS "code" text'
    )
    # Backfill: partners.hooks.sync (SYNC_HOOK)
