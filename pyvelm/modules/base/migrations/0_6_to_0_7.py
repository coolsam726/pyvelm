"""Drop legacy multi-company ir.rule for res.partner."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)
    schema.delete_rows(
        "ir_rule", model="res.partner", name="res.partner: company scope"
    )
