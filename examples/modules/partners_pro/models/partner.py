"""partners_pro extension of res.partner.

Demonstrates Stage 7 _inherit:
  - adds a `vip_note` Char field to the base partner model
  - overrides `_compute_display_name` to prefix VIP partners
"""
from pyvelm import BaseModel, Char, depends


class PartnerPro(BaseModel):
    """Extension: adds VIP fields and method override to res.partner."""

    _inherit = "res.partner"

    vip_note = Char(string="VIP Note")

    # Override the compute method so VIP partners show a prefix.
    # super() chains back to the original Partner._compute_display_name.
    @depends("name", "country_id.code", "country_id.region_id.name", "vip_note")
    def _compute_display_name(self):
        super()._compute_display_name()
        for r in self:
            if r.vip_note:
                current = r.env.cache.get(r._name, r.id, "display_name")
                r.env.cache.set(
                    r._name, r.id, "display_name", f"★ {current}"
                )
