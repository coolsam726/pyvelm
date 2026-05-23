"""Add ``birth_date`` to res.partner for the date picker demo."""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_partner" '
        'ADD COLUMN IF NOT EXISTS "birth_date" date'
    )
