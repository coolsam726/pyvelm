"""Introduce ir.attachment and Admin ACL."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _attachment(t):
        t.string("name", nullable=False)
        t.string("datas_fname", nullable=True)
        t.string("mimetype", nullable=True)
        t.integer("file_size", nullable=True)
        t.string("res_model", nullable=True)
        t.integer("res_id", nullable=True)
        t.string("type", nullable=True)
        t.string("url", nullable=True)
        t.string("storage_key", nullable=True)
        t.text("datas", nullable=True)
        t.index("res_model", "res_id", name="ir_attachment_res_idx")

    schema.create("ir_attachment", _attachment)

    if "ir.model.access" in env.registry and "res.groups" in env.registry:
        Access = env["ir.model.access"]
        Group = env["res.groups"]
        admin = Group.search([("name", "=", "Admin")], limit=1)
        if admin and not Access.search(
            [("model", "=", "ir.attachment"), ("group_id", "=", admin.id)],
            limit=1,
        ):
            Access.create(
                {
                    "name": "Admin/ir.attachment",
                    "model": "ir.attachment",
                    "group_id": admin,
                    "perm_read": True,
                    "perm_write": True,
                    "perm_create": True,
                    "perm_unlink": True,
                }
            )
