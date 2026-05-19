"""Install / upgrade hooks for the base module.

`install(env)` runs on first install only (after schema setup, before
view sync). Seeds a default Admin group and a superuser with id=1
plus a Public group for unauthenticated access grants.
"""


def install(env):
    Group = env["res.groups"]
    User = env["res.users"]

    admin_group = Group.create({"name": "Admin"})
    Group.create({"name": "Public"})

    # Seed the default company before creating users/partners so that
    # FK constraints are satisfied.
    company = None
    if "res.company" in env.registry:
        company = env["res.company"].create({"name": "My Company", "active": True})

    # The superuser is hard-coded to uid=1 — that's what
    # `Environment.is_superuser()` checks. Postgres SERIAL hands out
    # 1 to the first INSERT, and we INSERT this user before any other
    # in the install lifecycle, so the convention holds.
    user_vals = {
        "name": "Administrator",
        "login": "admin",
        "password": "admin",   # bcrypt-hashed by the Password field
        "group_ids": [admin_group],
    }
    if company is not None:
        user_vals["company_id"] = company
    User.create(user_vals)

    # Grant Admin full CRUD on Stage 6 workflow models.
    if "ir.model.access" in env.registry:
        Access = env["ir.model.access"]
        for model in (
            "ir.actions.server",
            "base.automation",
            "ir.cron",
            "mail.message",
            "res.company",
        ):
            if model in env.registry:
                Access.create({
                    "name": f"Admin/{model}",
                    "model": model,
                    "group_id": admin_group,
                    "perm_read": True,
                    "perm_write": True,
                    "perm_create": True,
                    "perm_unlink": True,
                })

    # Company-scoped record rule for res.partner: non-superusers see only
    # partners that belong to their current company (or have no company).
    # The placeholder is substituted with env.company_id at query time.
    import json
    if "ir.rule" in env.registry and "res.partner" in env.registry:
        env["ir.rule"].create({
            "name": "res.partner: company scope",
            "model": "res.partner",
            "group_id": None,  # global rule — applies to all users
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
            "domain": json.dumps([
                ["company_id", "in", [{"placeholder": "company_id"}, False]],
            ]),
        })
