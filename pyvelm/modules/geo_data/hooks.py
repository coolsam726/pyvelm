"""Install hook for geo_data — seed continents, countries, states, cities.

Data sources
------------
- ``geonamescache.GeonamesCache`` — continents (7), countries (252 with
  continent / ISO3 / phone / currency / capital / population), cities
  (≈32k, filtered down to capitals + population ≥ 100,000).
- ``pycountry.subdivisions`` — ISO 3166-2 subdivisions (≈5,000),
  linked to the country by ISO alpha-2.

Both packages are optional dependencies. The install hook imports them
lazily and surfaces a clear ``pip install pyvelm[geo]`` error when
either is missing.

Idempotency
-----------
The hook is safe to re-run: existing rows are matched on their
natural keys (continent ``code``, country ``code``, state ``code``,
city ``geoname_id``) and only the missing ones are inserted. The
loader installs each module inside a transaction, so a partial seed
either commits in full or rolls back.
"""

from __future__ import annotations

import logging

from pyvelm.geo_utils import flag_emoji as _flag_emoji
from pyvelm.geo_utils import require_geo_packages as _require_packages

log = logging.getLogger("pyvelm.geo_data")

_CITY_POPULATION_THRESHOLD = 100_000


def install(env):
    _require_packages()
    import geonamescache
    import pycountry

    gc = geonamescache.GeonamesCache()

    _grant_acl(env)
    continents = _seed_continents(env, gc)
    countries = _seed_countries(env, gc, continents)
    states = _seed_states(env, pycountry, countries)
    _seed_cities(env, gc, countries, states)


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


def _seed_continents(env, gc) -> dict[str, int]:
    """Insert any continent not yet present; return ``{code: id}``."""
    Continent = env["res.continent"]
    existing = {c.code: c.id for c in Continent.search([])}
    inserted = 0
    for code, payload in gc.get_continents().items():
        if code in existing:
            continue
        rec = Continent.create({"name": payload.get("name") or code, "code": code})
        existing[code] = rec.id
        inserted += 1
    if inserted:
        log.info("geo_data: inserted %d continents", inserted)
    return existing


def _seed_countries(env, gc, continents: dict[str, int]) -> dict[str, int]:
    """Insert / patch countries; return ``{iso_alpha2: id}``."""
    Country = env["res.country"]
    existing_by_code: dict[str, int] = {}
    for c in Country.search([]):
        if c.code:
            existing_by_code[c.code.upper()] = c.id
    inserted = 0
    patched = 0
    out: dict[str, int] = {}
    for iso2, payload in gc.get_countries().items():
        vals = {
            "name": payload.get("name") or iso2,
            "code": iso2,
            "iso3": payload.get("iso3") or None,
            "phone_code": payload.get("phone") or None,
            "currency_code": payload.get("currencycode") or None,
            "capital": payload.get("capital") or None,
            "population": int(payload.get("population") or 0) or None,
            "flag_emoji": _flag_emoji(iso2) or None,
            "continent_id": continents.get(payload.get("continentcode") or "")
            or None,
        }
        if iso2 in existing_by_code:
            # Patch existing rows so re-installs pick up upstream fixes.
            rec = Country.browse(existing_by_code[iso2])
            rec.write({k: v for k, v in vals.items() if v is not None})
            out[iso2] = rec.id
            patched += 1
            continue
        rec = Country.create(vals)
        out[iso2] = rec.id
        inserted += 1
    if inserted or patched:
        log.info(
            "geo_data: countries — %d inserted, %d patched", inserted, patched
        )
    return out


def _seed_states(env, pycountry, countries: dict[str, int]) -> dict[str, int]:
    """Insert any ISO 3166-2 subdivision not yet present.

    Returns ``{(country_iso2, admin1_code): state_id}`` so the city
    seeder can resolve ``admin1code`` to the right state.
    """
    State = env["res.country.state"]
    existing = {s.code: s.id for s in State.search([])}
    inserted = 0
    by_country_admin1: dict[tuple[str, str], int] = {}
    for sub in pycountry.subdivisions:
        iso2 = (sub.country_code or "").upper()
        country_id = countries.get(iso2)
        if not country_id:
            continue
        code = sub.code  # "US-CA"
        short_code = code.split("-", 1)[-1] if "-" in code else code
        if code in existing:
            by_country_admin1[(iso2, short_code)] = existing[code]
            continue
        rec = State.create(
            {
                "name": sub.name,
                "code": code,
                "short_code": short_code,
                "type": getattr(sub, "type", None) or None,
                "country_id": country_id,
            }
        )
        existing[code] = rec.id
        by_country_admin1[(iso2, short_code)] = rec.id
        inserted += 1
    if inserted:
        log.info("geo_data: inserted %d states/subdivisions", inserted)
    return by_country_admin1


def _seed_cities(env, gc, countries: dict[str, int], states: dict[tuple[str, str], int]) -> None:
    """Seed capitals + cities with population ≥ 100k."""
    City = env["res.city"]
    Country = env["res.country"]

    # Resolve "capital city name" per country once so the seeder can
    # flag capitals even when their population falls below the
    # threshold (e.g. Vaduz, ~5,500).
    capitals_by_iso2: dict[str, str] = {
        iso2: (payload.get("capital") or "").strip().lower()
        for iso2, payload in gc.get_countries().items()
        if payload.get("capital")
    }

    existing_geoname_ids = {
        c.geoname_id for c in City.search([]) if c.geoname_id
    }
    inserted = 0
    cities = gc.get_cities()
    for gid, payload in cities.items():
        gid_int = int(gid) if not isinstance(gid, int) else gid
        if gid_int in existing_geoname_ids:
            continue
        iso2 = (payload.get("countrycode") or "").upper()
        country_id = countries.get(iso2)
        if not country_id:
            continue
        name = payload.get("name") or ""
        population = int(payload.get("population") or 0)
        is_capital = (
            name.strip().lower() == capitals_by_iso2.get(iso2, "")
            if capitals_by_iso2.get(iso2)
            else False
        )
        if population < _CITY_POPULATION_THRESHOLD and not is_capital:
            continue
        admin1 = (payload.get("admin1code") or "").upper()
        state_id = states.get((iso2, admin1)) if admin1 else None
        City.create(
            {
                "name": name,
                "country_id": country_id,
                "state_id": state_id,
                "latitude": float(payload.get("latitude") or 0.0),
                "longitude": float(payload.get("longitude") or 0.0),
                "population": population or None,
                "timezone": payload.get("timezone") or None,
                "geoname_id": gid_int,
                "is_capital": is_capital,
            }
        )
        inserted += 1
    if inserted:
        log.info("geo_data: inserted %d cities", inserted)
