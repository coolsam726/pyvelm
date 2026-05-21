"""Migration 0.17.0 → 0.18.0 — add ``res.users.avatar_url``.

Single additive column; existing rows keep ``NULL`` (no avatar set).
The user form's image widget reads NULL as "no image" and renders the
initial-circle placeholder, so existing installs see a no-op visual
change until users actually upload or paste a URL.

Fresh installs pick the column up through ``_setup_table``'s
``ADD COLUMN IF NOT EXISTS`` second pass.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_users" '
        'ADD COLUMN IF NOT EXISTS "avatar_url" text'
    )
