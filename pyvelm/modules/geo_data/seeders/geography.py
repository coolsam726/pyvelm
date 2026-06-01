"""Geography reference-data seeders (geonamescache + pycountry)."""
from __future__ import annotations

import logging
from typing import Any

from pyvelm.geo_utils import flag_emoji as _flag_emoji
from pyvelm.geo_utils import geo_packages_available, require_geo_packages
from pyvelm.seeding import Seeder

log = logging.getLogger("pyvelm.geo_data")

_CITY_POPULATION_THRESHOLD = 100_000


class ContinentSeeder(Seeder):
    """Insert the seven GeoNames continents."""

    def run_instance(self, env, **context: Any) -> dict[str, int]:
        gc = context["gc"]
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


class CountrySeeder(Seeder):
    """Insert or patch countries from geonamescache."""

    def run_instance(self, env, *, continents: dict[str, int], **context: Any) -> dict[str, int]:
        gc = context["gc"]
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


class StateSeeder(Seeder):
    """Insert ISO 3166-2 subdivisions via pycountry."""

    def run_instance(
        self, env, *, countries: dict[str, int], **context: Any
    ) -> dict[tuple[str, str], int]:
        import pycountry

        State = env["res.country.state"]
        existing = {s.code: s.id for s in State.search([])}
        inserted = 0
        by_country_admin1: dict[tuple[str, str], int] = {}
        for sub in pycountry.subdivisions:
            iso2 = (sub.country_code or "").upper()
            country_id = countries.get(iso2)
            if not country_id:
                continue
            code = sub.code
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


class CitySeeder(Seeder):
    """Seed capitals and cities with population ≥ 100k."""

    def run_instance(
        self,
        env,
        *,
        countries: dict[str, int],
        states: dict[tuple[str, str], int],
        **context: Any,
    ) -> int:
        gc = context["gc"]
        City = env["res.city"]

        capitals_by_iso2: dict[str, str] = {
            iso2: (payload.get("capital") or "").strip().lower()
            for iso2, payload in gc.get_countries().items()
            if payload.get("capital")
        }

        existing_geoname_ids = {
            c.geoname_id for c in City.search([]) if c.geoname_id
        }
        inserted = 0
        for gid, payload in gc.get_cities().items():
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
        return inserted


class GeographyDatabaseSeeder(Seeder):
    """Orchestrate continent → country → state → city seeding."""

    @classmethod
    def should_run(cls, env, **context: Any) -> bool:  # noqa: ARG003
        if not geo_packages_available():
            log.info(
                "geo_data: geography seed skipped — install extras: pip install pyvelm[geo]"
            )
            return False
        return True

    def run_instance(self, env, **context: Any) -> dict[str, int]:
        require_geo_packages()
        import geonamescache

        gc = geonamescache.GeonamesCache()
        ctx = {"gc": gc, **context}
        counts = {"continents": 0, "countries": 0, "states": 0, "cities": 0}

        before = len(env["res.continent"].search([]))
        continent_map = self.call(env, ContinentSeeder, **ctx)
        counts["continents"] = len(env["res.continent"].search([])) - before

        before = len(env["res.country"].search([]))
        countries = self.call(
            env, CountrySeeder, continents=continent_map, **ctx
        )
        counts["countries"] = len(env["res.country"].search([])) - before

        before = len(env["res.country.state"].search([]))
        states = self.call(env, StateSeeder, countries=countries, **ctx)
        counts["states"] = len(env["res.country.state"].search([])) - before

        before = len(env["res.city"].search([]))
        cities_added = self.call(
            env, CitySeeder, countries=countries, states=states, **ctx
        )
        counts["cities"] = cities_added if cities_added else (
            len(env["res.city"].search([])) - before
        )
        return counts
