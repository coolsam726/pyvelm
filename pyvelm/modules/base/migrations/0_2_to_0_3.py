"""Add ACL schema: res.groups, res.users, ir.model.access, ir.rule."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    schema.create("res_groups", lambda t: t.string("name", nullable=False))

    def _users(t):
        t.string("name", nullable=False)
        t.string("login", nullable=False)
        t.string("password")
        t.boolean("active")

    schema.create("res_users", _users)

    def _rel(t):
        t.foreign_id("res_groups_id", "res_groups", ondelete="CASCADE", nullable=False)
        t.foreign_id("res_users_id", "res_users", ondelete="CASCADE", nullable=False)
        t.primary_key("res_groups_id", "res_users_id")

    schema.create("res_groups_res_users_rel", _rel)

    def _access(t):
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.foreign_id("group_id", "res_groups", ondelete="SET NULL", nullable=True)
        t.boolean("perm_read")
        t.boolean("perm_write")
        t.boolean("perm_create")
        t.boolean("perm_unlink")

    schema.create("ir_model_access", _access)

    def _rule(t):
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.foreign_id("group_id", "res_groups", ondelete="SET NULL", nullable=True)
        t.boolean("perm_read")
        t.boolean("perm_write")
        t.boolean("perm_create")
        t.boolean("perm_unlink")
        t.text("domain", nullable=False)

    schema.create("ir_rule", _rule)
