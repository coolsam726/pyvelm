"""Migration 0.24.0 → 0.25.0 — classify UI-chrome attachments as public.

``ir.attachment`` gained a ``public`` flag: logos, favicons, and avatars
must be served without an ``ir.attachment`` read grant (that's why
non-admins saw a broken logo). The column is added by the schema sync;
this backfills existing rows referenced by company branding / user
avatar fields. New uploads set the flag at upload time.
"""


def migrate(env):
    from base import hooks

    hooks.classify_chrome_attachments_public(env)
