"""Install hook for the admin module.

Grants Admin full CRUD on the four ACL models so operators can manage
groups, users, access entries, and record rules through the UI.
No new seed data — the base module already seeds the Admin group and
uid=1 superuser.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    for model in ("res.groups", "res.users", "ir.model.access", "ir.rule"):
        Access.create({
            "name": f"Admin/{model}",
            "model": model,
            "group_id": admin,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        })
