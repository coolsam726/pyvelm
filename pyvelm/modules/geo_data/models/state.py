"""``res.country.state`` — ISO 3166-2 country subdivisions.

Identified by the ISO 3166-2 ``code`` (e.g. ``US-CA``). The
``short_code`` is the part after the dash (``CA``) for compact
display in addresses. ``type`` carries pycountry's label (``State``,
``Province``, ``Region``, …) so apps can group by subdivision type
when relevant.
"""

from pyvelm import BaseModel, Char, Many2one, depends


class CountryState(BaseModel):
    _name = "res.country.state"
    _rec_name = "name"

    name = Char(required=True, string="Name")
    code = Char(required=True, string="ISO 3166-2")
    short_code = Char(string="Short code")
    type = Char(string="Type")
    country_id = Many2one("res.country", ondelete="CASCADE")
    parent_id = Many2one("res.country.state", ondelete="SET NULL")

    @depends("name", "short_code", "code")
    def _compute_display_name(self):
        for r in self:
            tag = r.short_code or r.code
            if r.name and tag:
                r.display_name = f"{r.name} ({tag})"
            else:
                r.display_name = r.name or r.code or f"res.country.state #{r.id}"
