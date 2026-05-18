from pyvelm import BaseModel, Char, Many2many


class Tag(BaseModel):
    _name = "res.tag"

    name = Char(required=True)
    partner_ids = Many2many("res.partner")
