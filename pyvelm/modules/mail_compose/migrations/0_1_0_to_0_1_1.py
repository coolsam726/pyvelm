"""Migration 0.1.0 → 0.1.1 — relax the NOT NULL on ``recipient_to``.

Drafts are legitimate without a To address (the auto-resolver may have
nothing to scan, or the operator hasn't picked recipients yet). The
``action_send`` method is the authoritative gate against dispatching
an empty To, so the column constraint is overkill — and
``Text.to_sql_param`` normalises ``""`` to ``NULL`` anyway, which
collided with the constraint on launch.
"""


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "mail_compose_message" '
        'ALTER COLUMN "recipient_to" DROP NOT NULL'
    )
