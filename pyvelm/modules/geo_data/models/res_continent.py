"""``res.continent`` — the seven continents.

Identified by ISO-like 2-letter code (``AF``, ``AS``, ``EU``, ``NA``,
``SA``, ``OC``, ``AN``) matching GeoNames' ``continentCode``. The
``res.country.continent_id`` FK pivots off this code.
"""

from pyvelm import Char, One2many, depends, models


class ResContinent(models.Model):
    _name = "res.continent"
    _rec_name = "name"

    name = Char(required=True, string="Name")
    code = Char(required=True, string="Code")
    country_ids = One2many("res.country", inverse_name="continent_id")

    @depends("name", "code")
    def _compute_display_name(self):
        for r in self:
            r.display_name = (
                f"{r.name} ({r.code})" if r.code else (r.name or "")
            )
