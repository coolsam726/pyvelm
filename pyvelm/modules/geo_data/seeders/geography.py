"""Geography reference-data seeders (geonamescache + pycountry)."""
from __future__ import annotations

import logging
import os
from typing import Any

from pyvelm.geo_utils import flag_emoji as _flag_emoji
from pyvelm.geo_utils import geo_packages_available, require_geo_packages
from pyvelm.seeding import (
    Seeder,
    bulk_insert_stored,
    fetch_column_map,
    fetch_int_column_set,
)

log = logging.getLogger("pyvelm.geo_data")

_CITY_POPULATION_THRESHOLD = 100_000
# GeoNames ships ~250 countries; treat DB as seeded when we already have most of them.
_COUNTRIES_SEEDED_THRESHOLD = 200
_BULK_CHUNK = 500


def _geo_seed_level(context: dict[str, Any]) -> str:
    return (
        (context.get("geo_seed_level") or os.environ.get("PYVELM_GEO_SEED_LEVEL") or "full")
        .strip()
        .lower()
    )


def _include_states(level: str) -> bool:
    return level in ("full", "states")


def _include_cities(level: str) -> bool:
    return level == "full"


class ContinentSeeder(Seeder):
    """Insert the seven GeoNames continents."""

    def run_instance(self, env, **context: Any) -> dict[str, int]:
        gc = context["gc"]
        Continent = env["res.continent"]
        existing = fetch_column_map(
            env,
            Continent._table,
            "code",
            model_cls=Continent,
            normalize_key="upper",
        )
        to_insert: list[dict[str, Any]] = []
        for code, payload in gc.get_continents().items():
            if code in existing:
                continue
            to_insert.append(
                {"name": payload.get("name") or code, "code": code}
            )
        inserted = bulk_insert_stored(env, Continent, to_insert)
        counts = context.get("inserted")
        if isinstance(counts, dict):
            counts["continents"] = inserted
        if inserted:
            log.info("geo_data: inserted %d continents", inserted)
        existing.update(
            fetch_column_map(
                env,
                Continent._table,
                "code",
                model_cls=Continent,
                normalize_key="upper",
            )
        )
        return existing


class CountrySeeder(Seeder):
    """Insert countries from geonamescache (batched; optional patch on re-seed)."""

    def run_instance(self, env, *, continents: dict[str, int], **context: Any) -> dict[str, int]:
        gc = context["gc"]
        Country = env["res.country"]
        existing = fetch_column_map(
            env,
            Country._table,
            "code",
            model_cls=Country,
            normalize_key="upper",
        )
        patch_existing = bool(context.get("patch_existing"))
        to_insert: list[dict[str, Any]] = []
        patched = 0
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
            if iso2 in existing:
                if patch_existing:
                    env["res.country"].browse(existing[iso2]).write(
                        {k: v for k, v in vals.items() if v is not None}
                    )
                    patched += 1
                continue
            to_insert.append(vals)
        inserted = bulk_insert_stored(env, Country, to_insert, chunk_size=_BULK_CHUNK)
        counts = context.get("inserted")
        if isinstance(counts, dict):
            counts["countries"] = inserted
        if inserted or patched:
            log.info(
                "geo_data: countries — %d inserted, %d patched", inserted, patched
            )
        existing.update(
            fetch_column_map(
                env,
                Country._table,
                "code",
                model_cls=Country,
                normalize_key="upper",
            )
        )
        return existing


class StateSeeder(Seeder):
    """Insert ISO 3166-2 subdivisions via pycountry."""

    def run_instance(
        self, env, *, countries: dict[str, int], **context: Any
    ) -> dict[tuple[str, str], int]:
        import pycountry

        State = env["res.country.state"]
        existing = fetch_column_map(
            env,
            State._table,
            "code",
            model_cls=State,
            normalize_key=None,
        )
        to_insert: list[dict[str, Any]] = []
        for sub in pycountry.subdivisions:
            iso2 = (sub.country_code or "").upper()
            country_id = countries.get(iso2)
            if not country_id:
                continue
            code = sub.code
            if code in existing:
                continue
            short_code = code.split("-", 1)[-1] if "-" in code else code
            to_insert.append(
                {
                    "name": sub.name,
                    "code": code,
                    "short_code": short_code,
                    "type": getattr(sub, "type", None) or None,
                    "country_id": country_id,
                }
            )
        inserted = bulk_insert_stored(env, State, to_insert, chunk_size=_BULK_CHUNK)
        counts = context.get("inserted")
        if isinstance(counts, dict):
            counts["states"] = inserted
        if inserted:
            log.info("geo_data: inserted %d states/subdivisions", inserted)
        by_country_admin1: dict[tuple[str, str], int] = {}
        for code, rid in fetch_column_map(
            env,
            State._table,
            "code",
            model_cls=State,
            normalize_key=None,
        ).items():
            if "-" in code:
                iso2, short = code.split("-", 1)[0].upper(), code.split("-", 1)[1]
                by_country_admin1[(iso2, short)] = rid
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

        existing_geoname_ids = fetch_int_column_set(
            env, City._table, "geoname_id", model_cls=City
        )
        to_insert: list[dict[str, Any]] = []
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
            to_insert.append(
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
        inserted = bulk_insert_stored(env, City, to_insert, chunk_size=_BULK_CHUNK)
        counts = context.get("inserted")
        if isinstance(counts, dict):
            counts["cities"] = inserted
        if inserted:
            log.info("geo_data: inserted %d cities", inserted)
        return inserted


class GeographyDatabaseSeeder(Seeder):
    """Orchestrate continent → country → state → city seeding."""

    @classmethod
    def should_run(cls, env, **context: Any) -> bool:
        if not geo_packages_available():
            log.info(
                "geo_data: geography seed skipped — install extras: pip install pyvelm[geo]"
            )
            return False
        if context.get("force"):
            return True
        if "res.country" in env.registry:
            if env["res.country"].search_count([]) >= _COUNTRIES_SEEDED_THRESHOLD:
                log.info("geo_data: geography seed skipped — countries already loaded")
                return False
        return True

    def run_instance(self, env, **context: Any) -> dict[str, int]:
        require_geo_packages()
        import geonamescache

        level = _geo_seed_level(context)
        gc = geonamescache.GeonamesCache()
        counts = {"continents": 0, "countries": 0, "states": 0, "cities": 0}
        ctx = {"gc": gc, "inserted": counts, **context}

        continent_map = self.call(env, ContinentSeeder, **ctx)
        countries = self.call(env, CountrySeeder, continents=continent_map, **ctx)

        if _include_states(level):
            states = self.call(env, StateSeeder, countries=countries, **ctx)
        else:
            states = {}
            log.info("geo_data: skipping states (PYVELM_GEO_SEED_LEVEL=%s)", level)

        if _include_cities(level):
            self.call(env, CitySeeder, countries=countries, states=states, **ctx)
        else:
            log.info("geo_data: skipping cities (PYVELM_GEO_SEED_LEVEL=%s)", level)

        return counts
