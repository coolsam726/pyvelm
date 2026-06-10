from pyvelm import (
    Date,
    Integer,
    Many2many,
    depends,
    fields,
    models,
)


class ResPartner(models.Model):
    _inherit = "res.partner"

    age = Integer()
    birth_date = Date(string="Birth date")
    tag_ids = Many2many("res.tag", tracking=True)

    age_bucket = fields.Char(compute="_compute_age_bucket", store=True)

    @depends("age")
    def _compute_age_bucket(self):
        for r in self:
            a = r.age or 0
            r.age_bucket = "senior" if a >= 40 else ("mid" if a >= 30 else "young")
