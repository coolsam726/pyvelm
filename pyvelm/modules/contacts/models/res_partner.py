from pyvelm import (
    Boolean,
    Char,
    Many2one,
    One2many,
    depends,
    models,
)


class ResPartner(models.Model):
    _name = "res.partner"
    _company_scoped = True

    name = Char(required=True, string="Name", tracking=True)
    code = Char(required=True, tracking=True)
    email = Char(string="Email")
    phone = Char(string="Phone")
    active = Boolean(default=True, tracking=True)
    country_id = Many2one("res.country", ondelete="SET NULL")
    parent_id = Many2one("res.partner", ondelete="SET NULL")
    child_ids = One2many("res.partner", inverse_name="parent_id")
    company_id = Many2one("res.company", ondelete="SET NULL")

    @depends("name", "country_id.code", "country_id.region_id.name")
    def _compute_display_name(self):
        for r in self:
            code = r.country_id.code if r.country_id else None
            region = (
                r.country_id.region_id.name
                if (r.country_id and r.country_id.region_id)
                else None
            )
            parts = [r.name]
            if code:
                parts.append(f"[{code}]")
            if region:
                parts.append(f"({region})")
            r.display_name = " ".join(parts)
