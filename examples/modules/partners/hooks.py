"""Install hook for the `partners` module.

Seeds the baseline access rules every install needs: Admin gets full
CRUD on partner-side models, and unauthenticated (group_id=None) gets
read on low-sensitivity geo data (countries, regions). Partners
themselves stay locked down — only Admin (or whatever groups
downstream modules grant access to) can read them.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    # Admin: full CRUD on partner-owned models.
    for model in ("res.partner", "res.tag"):
        Access.create({
            "name": f"Admin/{model}",
            "model": model,
            "group_id": admin,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        })

    # Anonymous: read-only on geo lookups (countries, regions).
    # Same convention as Odoo's "Public" group, modeled via
    # group_id=None for "applies to everyone, including unauth."
    for model in ("res.country", "res.region"):
        Access.create({
            "name": f"Public/{model}",
            "model": model,
            "group_id": None,
            "perm_read": True,
        })
