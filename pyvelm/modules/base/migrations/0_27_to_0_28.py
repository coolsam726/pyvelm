"""Migration 0.27.0 → 0.28.0 — ``ir.ui.menu.dev_only`` flag.

Adds the ``dev_only`` Boolean column on ``ir.ui.menu``. Fresh installs
pick it up via ``_setup_table``; existing databases get it via schema
autogen (nullable Boolean with no backfill — every existing menu stays
visible because ``False`` is the default).
"""


def migrate(env):
    return None
