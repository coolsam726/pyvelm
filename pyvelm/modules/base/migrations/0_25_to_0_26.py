"""Migration 0.25.0 → 0.26.0 — email templates (``mail.template``).

Schema sync adds ``mail.template`` and new ``mail.message`` columns.
This backfills Admin ACL on existing databases.
"""


def migrate(env):
    from pyvelm.security import grant_model_access

    grant_model_access(env, "mail.template", admin="crud", user=None, public=None)
