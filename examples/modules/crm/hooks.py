"""Install hook for the crm module.

Seeds access grants so Admin can fully manage CRM leads.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    Access.create({
        "name": "Admin/crm.lead",
        "model": "crm.lead",
        "group_id": admin,
        "perm_read": True,
        "perm_write": True,
        "perm_create": True,
        "perm_unlink": True,
    })
