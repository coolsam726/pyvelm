"""Migration 0.21.0 → 0.22.0 — read access on ``ir.ui.view`` for all users.

Non-admin web sessions load view arch via ``ir.ui.view.search``; without
a global read grant they raise ``PermissionError``. Fresh installs get
the same row from ``base.hooks:install``; this backfills existing DBs.
"""


def migrate(env):
    from base import hooks

    hooks._seed_ui_view_read_access(env)
    if "ir.model.access" not in env.registry or "res.groups" not in env.registry:
        return
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")], limit=1)
    if not admin:
        return
    if "ir.ui.view" not in env.registry:
        return
    if Access.search(
        [("model", "=", "ir.ui.view"), ("group_id", "=", admin.id)],
        limit=1,
    ):
        return
    Access.create(
        {
            "name": "Admin/ir.ui.view",
            "model": "ir.ui.view",
            "group_id": admin,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        }
    )
