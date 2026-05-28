"""Migration 0.29.0 → 0.30.0 — company stamp on ``ir.attachment``.

Adds the nullable ``company_id`` column the file_manager library uses
to scope its view per company. Fresh installs get it through
``_setup_table``; this explicit ``ALTER`` is the safety net for
databases that update base before re-installing file_manager. No
backfill — existing attachments stay company-less (they simply don't
appear in a company-scoped library, which is the intended behaviour
for system attachments like avatars / mail).
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "ir_attachment" '
        'ADD COLUMN IF NOT EXISTS "company_id" INTEGER NULL'
    )
