"""Migration 0.26.0 → 0.27.0 — multi-recipient outgoing mail.

Adds ``recipient_cc``, ``recipient_bcc``, ``reply_to`` to ``mail.message``.
Fresh installs pick these columns up through ``_setup_table``; on existing
databases the schema-autogen step adds them as nullable text columns. No
data backfill is needed — every existing row stays valid with the new
columns set to NULL (single-recipient send still works).
"""


def migrate(env):
    return None
