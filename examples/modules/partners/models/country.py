"""Contribute the reverse `partner_ids` relation to res.country.

``base`` owns `res.country`, but the reverse-side One2many to
`res.partner` can't live there — base must stay installable without
the partners module. The partners module adds the field via
``_inherit`` so the relation only exists when both sides are loaded.
"""
from pyvelm import BaseModel, One2many


class Country(BaseModel):
    _inherit = "res.country"

    partner_ids = One2many("res.partner", "country_id")
