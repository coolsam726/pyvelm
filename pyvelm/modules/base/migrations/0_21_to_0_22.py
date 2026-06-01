"""Read access on ir.ui.view for all users."""

from base import hooks


def upgrade(env):
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
