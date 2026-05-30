# Geo data (`geo_data` module)

A bundled module that ships seed data for the world's geography:
**7 continents**, **~250 countries** (with ISO-3, phone code,
currency, capital, population, flag emoji), **~5,000
states / provinces** (ISO 3166-2), and **~6,000 cities** (every
country capital plus every city with population ≥ 100,000).

## Install

The module depends on two upstream packages that aren't part of the
default pyvelm wheel — install the geo extras first:

```bash
pip install pyvelm[geo]
```

Then install the module from **Apps**, or include it in your
`loader.load_and_install(...)` call. Install creates the tables and ACLs
only — tables start **empty**.

To load reference data, open **Settings → Geography → Countries** and
click **Seed geography data** (requires `pyvelm[geo]` and superuser).
The seed reads `geonamescache` + `pycountry` in one transaction.

The seed is **idempotent**: existing rows are matched on their
natural keys (continent `code`, country `code`, state `code`, city
`geoname_id`) and only the missing ones are inserted. Existing
country rows are patched with any extra fields the seeder knows
about (ISO-3, phone code, etc.), so re-installing after a pyvelm
upgrade picks up upstream fixes.

## Models

| Model | Rows | Identity | Notes |
|-------|------|----------|-------|
| `res.continent` | 7 | `code` (AF, AS, EU, NA, SA, OC, AN) | Matches GeoNames' `continentCode`. |
| `res.country` (extended) | ~250 | `code` (ISO 3166-1 alpha-2) | Adds `continent_id`, `iso3`, `phone_code`, `currency_code`, `capital`, `population`, `flag_emoji`. The legacy `region_id` stays for backward compatibility. |
| `res.country.state` | ~5,000 | `code` (ISO 3166-2, e.g. `US-CA`) | `short_code` is the part after the dash (`CA`). `type` carries pycountry's label (`State`, `Province`, `Region`, …). |
| `res.city` | ~6,000 | `geoname_id` | `is_capital` is True for the country's capital city. `latitude` / `longitude` are stored as Float. |

`display_name` is overridden on every model so combobox pickers
render usefully out of the box:

| Model | Format |
|-------|--------|
| `res.continent` | `{name} ({code})` |
| `res.country` | `{flag_emoji} {name}` |
| `res.country.state` | `{name} ({short_code})` |
| `res.city` | `{name}, {state.short_code or country.code}` |

## Country form (notebook demo)

The **Countries** form (`geo_data.country.form`) demonstrates **[Form UX](form-ux.md)**
features:

- Flat **Identity** and **Facts** sections for scalar fields.
- A **Subdivisions** notebook with **States / provinces** and **Cities** tabs.
- `state_ids` and `city_ids` each use **`edit_toggle=True`** with compact
  list views (`geo_data.state.compact`, `geo_data.city.compact`) so users can
  switch between dialog lines and an inline grid on the parent **Edit** form.

After upgrading to **geo_data 0.1.3+**, run **`pyvelm db migrate`** (or Apps →
Sync) so `ir.ui.view` picks up the arch.

## Sidebar

Adds **Settings → Geography** with four leaves:

- Continents
- Countries
- States / provinces
- Cities

ACL: **Admin** gets full CRUD on all four models; **User** gets
read so non-admins can reference geo rows from their own forms even
though they can't edit them.

## Data sources

- **`geonamescache`** — continents, countries (with `continent`,
  `iso3`, `phone`, `currencycode`, `capital`, `population`), and
  ~32,000 cities. The seeder filters cities to capitals + population
  ≥ 100,000 by default; raise that threshold by editing the module
  or call `_seed_cities()` yourself if you need a larger set.
- **`pycountry`** — authoritative ISO 3166-2 subdivisions, joined to
  countries by ISO alpha-2.

## Usage from your own modules

```python
from pyvelm import BaseModel, Char, Many2one


class Customer(BaseModel):
    _name = "crm.customer"
    name = Char(required=True)
    country_id = Many2one("res.country")
    state_id = Many2one("res.country.state")
    city_id = Many2one("res.city")
```

The standard Many2one combobox already searches by `display_name`,
so picking "California" or "🇫🇷 France" works without any extra
widget configuration.
