"""Contribute the reverse ``partner_ids`` relation to ``res.country``.

``base`` owns ``res.country``, but the reverse-side One2many to
``res.partner`` lives here so ``base`` stays installable without
``contacts``.
"""
from pyvelm import One2many, models


class ResCountry(models.Model):
    _inherit = "res.country"

    partner_ids = One2many("res.partner", "country_id")
