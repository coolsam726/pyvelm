"""Add ACL schema: res.groups, res.users, ir.model.access, ir.rule."""

from pyvelm.migrations import Blueprint, Schema, Table


def upgrade(env):
    schema = Schema(env)

    def _groups(t: Table) -> None:
        t.string("name", nullable=False)

    schema.create("res_groups", _groups)

    def _users(t: Table) -> None:
        t.string("name", nullable=False)
        t.string("login", nullable=False)
        t.string("password")
        t.boolean("active")

    schema.create("res_users", _users)

    def _rel(t: Table) -> None:
        t.foreign_id("res_groups_id", "res_groups", ondelete="CASCADE", nullable=False)
        t.foreign_id("res_users_id", "res_users", ondelete="CASCADE", nullable=False)
        t.primary_key("res_groups_id", "res_users_id")

    schema.create("res_groups_res_users_rel", _rel)

    def _access(t: Table) -> None:
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.foreign_id("group_id", "res_groups", ondelete="SET NULL", nullable=True)
        t.boolean("perm_read")
        t.boolean("perm_write")
        t.boolean("perm_create")
        t.boolean("perm_unlink")

    schema.create("ir_model_access", _access)

    def _rule(t: Table) -> None:
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.foreign_id("group_id", "res_groups", ondelete="SET NULL", nullable=True)
        t.boolean("perm_read")
        t.boolean("perm_write")
        t.boolean("perm_create")
        t.boolean("perm_unlink")
        t.text("domain", nullable=False)

    schema.create("ir_rule", _rule)
