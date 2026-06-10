"""Install hook for the ``partners`` example module.

Extends the bundled ``contacts`` module with tags and demo fields.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    Access.create({
        "name": "Admin/res.tag",
        "model": "res.tag",
        "group_id": admin,
        "perm_read": True,
        "perm_write": True,
        "perm_create": True,
        "perm_unlink": True,
    })
