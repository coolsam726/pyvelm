"""Install hook for file_manager.

Grants Admin full CRUD on ``ir.attachment`` and ``read`` to regular
Users so they can pick existing files via the file picker even though
they can't always reach the management UI. Public attachments stay
visible without ACL via the existing ``public=True`` short-circuit
on the download endpoint.
"""


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]

    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()
    user = Group.search([("name", "=", "User")])

    def _grant(group, model: str, *, write: bool):
        existing = Access.search(
            [("model", "=", model), ("group_id", "=", group.id)]
        )
        vals = {
            "perm_read": True,
            "perm_write": write,
            "perm_create": write,
            "perm_unlink": write,
        }
        if existing:
            existing.write(vals)
            return
        Access.create(
            {
                "name": f"file_manager/{group.name}/{model}",
                "model": model,
                "group_id": group,
                **vals,
            }
        )

    _grant(admin, "ir.attachment", write=True)
    if user:
        _grant(user, "ir.attachment", write=False)
