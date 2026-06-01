"""Install hook and geography seed entry points for geo_data.

Reference data is loaded by :class:`geo_data.seeders.GeographyDatabaseSeeder`
(registered in ``seeders/__init__.py``). The loader runs it on install,
upgrade, and Sync when ``pyvelm[geo]`` is installed. Use **Seed geography
data** on the Countries list or ``POST /web/geo-data/seed`` to force a run.
"""
from __future__ import annotations

import logging

log = logging.getLogger("pyvelm.geo_data")


def install(env):
    """Grant ACLs. Geography rows are seeded via ``SEEDERS`` in the manifest."""
    _grant_acl(env)


def seed_reference_data(env) -> dict[str, int]:
    """Load continents, countries, states, and cities (on demand).

    Returns counts ``{continents, countries, states, cities}`` inserted
    on this run (existing rows are skipped or patched).
    """
    from geo_data.seeders.geography import GeographyDatabaseSeeder

    result = GeographyDatabaseSeeder.run(env)
    if result is None:
        return {"continents": 0, "countries": 0, "states": 0, "cities": 0}
    return result


def _grant_acl(env) -> None:
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()
    user = Group.search([("name", "=", "User")])

    def _grant(group, model: str, *, write: bool) -> None:
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
                "name": f"geo_data/{group.name}/{model}",
                "model": model,
                "group_id": group,
                **vals,
            }
        )

    for model in (
        "res.continent",
        "res.country",
        "res.country.state",
        "res.city",
    ):
        _grant(admin, model, write=True)
        if user:
            _grant(user, model, write=False)
