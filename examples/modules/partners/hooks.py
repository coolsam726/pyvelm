"""Install hook for the `partners` module.

Seeds the baseline access rules every install needs: Admin gets full
CRUD on partner-side models, and unauthenticated (group_id=None) gets
read on low-sensitivity geo data (countries, regions). Partners
themselves stay locked down — only Admin (or whatever groups
downstream modules grant access to) can read them.
"""


def _backfill_partner_codes(env) -> None:
    """Idempotent: fill ``code`` from name + id (same as ``0_1_to_0_2`` migration)."""
    if "res.partner" not in env.registry:
        return
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"


def sync(env):
    """Runs before schema apply on upgrade/migrate/Sync — backfill then SET NOT NULL.

    Idempotent data fixups and orphan-column drops belong here (not only in
    ``migrations/*.py``), because migration bodies run once per version gap while
    this hook runs on every ``db migrate`` and Apps Sync.
    """
    _backfill_partner_codes(env)


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
