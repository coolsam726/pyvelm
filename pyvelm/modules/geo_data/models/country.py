"""Extend ``res.country`` with continent / ISO3 / phone / currency.

base ships ``res.country`` with just name + code + region_id. This
module adds the typical geo fields seeded from GeoNames so apps that
need address / locale data don't have to roll their own.

The legacy ``region_id`` Many2one(res.region) stays in place for
backward compatibility; new code should prefer ``continent_id``,
which is the authoritative parent in the geo hierarchy.
"""

from pyvelm import BaseModel, Char, Integer, Many2one, One2many, depends


class Country(BaseModel):
    _inherit = "res.country"

    continent_id = Many2one("res.continent", ondelete="SET NULL")
    iso3 = Char(string="ISO-3")
    phone_code = Char(string="Phone code")
    currency_code = Char(string="Currency code")
    capital = Char(string="Capital")
    population = Integer(string="Population")
    flag_emoji = Char(string="Flag")

    state_ids = One2many("res.country.state", inverse_name="country_id")
    city_ids = One2many("res.city", inverse_name="country_id")

    @depends("name", "code", "flag_emoji")
    def _compute_display_name(self):
        for r in self:
            if r.flag_emoji and r.name:
                r.display_name = f"{r.flag_emoji} {r.name}"
            elif r.name:
                r.display_name = r.name
            elif r.code:
                r.display_name = r.code
            else:
                r.display_name = f"res.country #{r.id}"
