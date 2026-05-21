"""Drop the legacy multi-company global ir.rule for res.partner.

0.6.0 install hooks seeded a global rule duplicating the
model-level `_company_scoped` filter applied by `BaseModel.search`.
The two contradicted each other (rule allowed NULL company_id;
model filter excluded it) and forced the env to carry a
`_rule_needs_company_skip` workaround. 0.7.0 standardizes on the
model-level filter only; this migration removes any stale rule from
older installs so they pick up the new semantics on upgrade.

Idempotent: the DELETE matches by (model, name) so re-runs are
no-ops.
"""


def migrate(env):
    env.conn.execute(
        'DELETE FROM "ir_rule" WHERE "model" = %s AND "name" = %s',
        ["res.partner", "res.partner: company scope"],
    )
