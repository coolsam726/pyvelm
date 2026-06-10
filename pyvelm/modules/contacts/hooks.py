"""Install hook for the bundled ``contacts`` module."""

from __future__ import annotations

from pyvelm.security import grant_model_access


def _backfill_partner_codes(env) -> None:
    """Idempotent: fill ``code`` from name + id when missing."""
    if "res.partner" not in env.registry:
        return
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"


def sync(env):
    """Runs on upgrade/migrate/Sync — backfill partner codes."""
    _backfill_partner_codes(env)


def install(env):
    grant_model_access(env, "res.partner", admin="crud", user=None)
    grant_model_access(env, "res.country", admin="crud", user="read", public="read")
    grant_model_access(env, "res.region", admin="crud", user="read", public="read")
