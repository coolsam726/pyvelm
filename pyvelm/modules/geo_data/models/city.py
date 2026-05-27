"""``res.city`` — populated cities + capitals from GeoNames.

Seeded with every country capital plus every city with population
≥ 100,000 (≈ 6,000 rows). ``geoname_id`` is the upstream identifier
(useful for joining external data); ``state_id`` is the linked
ISO 3166-2 subdivision when GeoNames' ``admin1code`` resolves to one
the seeder already created.

Lat/lng are stored as Float so map widgets can read them without
parsing. ``population`` is denormalised for sorting.
"""

from pyvelm import BaseModel, Boolean, Char, Float, Integer, Many2one, depends


class City(BaseModel):
    _name = "res.city"
    _rec_name = "name"

    name = Char(required=True, string="Name")
    country_id = Many2one("res.country", ondelete="CASCADE")
    state_id = Many2one("res.country.state", ondelete="SET NULL")
    latitude = Float(string="Latitude")
    longitude = Float(string="Longitude")
    population = Integer(string="Population")
    timezone = Char(string="Timezone")
    geoname_id = Integer(string="GeoNames ID")
    is_capital = Boolean(default=False, string="Capital")

    @depends("name", "state_id", "country_id")
    def _compute_display_name(self):
        for r in self:
            if not r.name:
                r.display_name = f"res.city #{r.id}"
                continue
            tag = ""
            if r.state_id and r.state_id.short_code:
                tag = r.state_id.short_code
            elif r.country_id and r.country_id.code:
                tag = r.country_id.code
            r.display_name = f"{r.name}, {tag}" if tag else r.name
