from pyvelm import BaseModel, Char, Many2one, One2many


class Country(BaseModel):
    _name = "res.country"

    name = Char(required=True)
    code = Char()
    region_id = Many2one("res.region", ondelete="SET NULL")
    partner_ids = One2many("res.partner", "country_id")
