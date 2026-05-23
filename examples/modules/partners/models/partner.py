from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Date,
    Integer,
    Many2many,
    Many2one,
    One2many,
    depends,
)


class Partner(BaseModel):
    _name = "res.partner"
    _company_scoped = True

    name = Char(required=True, string="Name")
    age = Integer()
    birth_date = Date(string="Birth date")
    active = Boolean(default=True)
    # Added in 0.2.0. Fresh installs create the column from this
    # declaration; upgrades from 0.1.0 get it via migrations/0_1_to_0_2.py
    # (ALTER TABLE ADD COLUMN + backfill).
    code = Char()
    country_id = Many2one("res.country", ondelete="SET NULL")
    parent_id = Many2one("res.partner", ondelete="SET NULL")
    child_ids = One2many("res.partner", inverse_name="parent_id")
    tag_ids = Many2many("res.tag")
    company_id = Many2one("res.company", ondelete="SET NULL")

    age_bucket = Char(compute="_compute_age_bucket", store=True)

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

    @depends("age")
    def _compute_age_bucket(self):
        for r in self:
            a = r.age or 0
            r.age_bucket = "senior" if a >= 40 else ("mid" if a >= 30 else "young")
