from pyvelm import BaseModel, Char, Many2one


class Country(BaseModel):
    _name = "res.country"

    name = Char(required=True)
    code = Char()
    region_id = Many2one("res.region", ondelete="SET NULL")
    # Reverse `partner_ids` is contributed by the `partners` example
    # addon via _inherit so base doesn't reference a model it doesn't
    # own — that would break installs that include base but not
    # partners.
