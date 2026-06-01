"""Add Stage 6 tables: ir_actions_server, base_automation, ir_cron, mail_message."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _actions_server(t):
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.string("action_type", nullable=False)
        t.text("vals_json")
        t.text("code")

    schema.create("ir_actions_server", _actions_server)

    def _automation(t):
        t.string("name", nullable=False)
        t.string("model", nullable=False)
        t.string("trigger", nullable=False)
        t.foreign_id("action_id", "ir_actions_server", ondelete="CASCADE")
        t.boolean("active")

    schema.create("base_automation", _automation)

    def _cron(t):
        t.string("name", nullable=False)
        t.foreign_id("action_id", "ir_actions_server", ondelete="CASCADE")
        t.integer("interval_number")
        t.string("interval_type")
        t.timestamp("nextcall")
        t.boolean("active")

    schema.create("ir_cron", _cron)

    def _mail_message(t):
        t.string("model")
        t.integer("res_id")
        t.foreign_id("author_id", "res_users", ondelete="SET NULL", nullable=True)
        t.text("body")
        t.string("message_type")
        t.string("subtype")
        t.timestamp("date")

    schema.create("mail_message", _mail_message)
