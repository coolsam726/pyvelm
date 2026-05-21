"""Outgoing-mail dispatcher: new mail.message columns + dispatcher cron.

mail.message gains four new columns (``recipient_email``, ``subject``,
``state``, ``error``) for the SMTP dispatcher introduced in Stage 6
Slice 2. Fresh installs get the columns via ``_setup_table`` from the
model declaration; upgraded installs add them here.

The dispatcher itself runs as an ``ir.cron`` whose server action
calls ``env["mail.message"].dispatch_outgoing()``. We seed both on
upgrade and let the hook re-seed on fresh installs — the search-
before-create pattern keeps the operation idempotent.

Idempotent: every DDL uses ``IF NOT EXISTS``; the seed steps look
the record up by name before creating.
"""


def migrate(env):
    # ---- column additions -----------------------------------------
    env.conn.execute(
        'ALTER TABLE "mail_message" '
        'ADD COLUMN IF NOT EXISTS "recipient_email" text'
    )
    env.conn.execute(
        'ALTER TABLE "mail_message" '
        'ADD COLUMN IF NOT EXISTS "subject" text'
    )
    env.conn.execute(
        "ALTER TABLE \"mail_message\" "
        "ADD COLUMN IF NOT EXISTS \"state\" text DEFAULT 'outgoing'"
    )
    env.conn.execute(
        'ALTER TABLE "mail_message" '
        'ADD COLUMN IF NOT EXISTS "error" text'
    )

    # ---- dispatcher action + cron ---------------------------------
    # Idempotent — both rows are looked up by name before creating.
    # Implementation lives in hooks._seed_mail_dispatcher so a fresh
    # install (which doesn't run this migration) calls the same code.
    from base import hooks
    hooks._seed_mail_dispatcher(env)
