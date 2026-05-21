from pyvelm import BaseModel, Boolean, Char, Float, Integer, Many2one, depends


class Lead(BaseModel):
    _name = "crm.lead"
    _company_scoped = True

    name = Char(required=True, string="Opportunity")
    partner_id = Many2one("res.partner", ondelete="SET NULL", string="Contact")
    stage = Char(string="Stage")  # new / qualified / proposal / won / lost
    priority = Integer(string="Priority")  # 0 low, 1 normal, 2 high
    expected_revenue = Float(string="Expected Revenue (k€)")
    probability = Integer(string="Probability %")
    salesperson = Char(string="Salesperson")
    active = Boolean(default=True)
    company_id = Many2one("res.company", ondelete="SET NULL")

    label = Char(compute="_compute_label", store=True, string="Label")

    @depends("stage", "priority")
    def _compute_label(self):
        _icons = {0: "○", 1: "●", 2: "★"}
        for r in self:
            icon = _icons.get(r.priority or 0, "●")
            r.label = f"{icon} {r.stage or 'new'}"
