"""Install hook for the technical module.

Grants Admin full CRUD on the low-level system models so the developer
sidebar entries actually work. Visibility is gated separately by the
``dev_only`` flag on the menu entries — even with the grants in place,
the entries are hidden whenever ``PYVELM_ENV != development``.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    for model in ("ir.ui.menu", "ir.ui.view", "ir.attachment"):
        existing = Access.search(
            [("model", "=", model), ("group_id", "=", admin.id)]
        )
        if existing:
            existing.write(
                {
                    "perm_read": True,
                    "perm_write": True,
                    "perm_create": True,
                    "perm_unlink": True,
                }
            )
            continue
        Access.create(
            {
                "name": f"Technical/{model}",
                "model": model,
                "group_id": admin,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )
