"""Add `Partner.code` and backfill from name + id.

Idempotent at the DDL level via ADD COLUMN IF NOT EXISTS so re-applying
the migration (which shouldn't happen, but defensive) doesn't fail. The
backfill only writes to rows whose `code` is still NULL, so existing
values are preserved.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_partner" ADD COLUMN IF NOT EXISTS "code" text'
    )
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"
