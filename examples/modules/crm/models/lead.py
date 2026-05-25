from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Date,
    Datetime,
    Float,
    Integer,
    Many2one,
    Time,
    depends,
)
from pyvelm.mail import MailThread


class Lead(MailThread, BaseModel):
    _name = "crm.lead"
    _company_scoped = True

    name = Char(required=True, string="Opportunity", tracking=True)
    partner_id = Many2one(
        "res.partner", ondelete="SET NULL", string="Contact", tracking=True
    )
    stage = Char(string="Stage", tracking=True)  # new / qualified / proposal / won / lost
    priority = Integer(string="Priority")  # 0 low, 1 normal, 2 high
    expected_revenue = Float(string="Expected Revenue (k€)", tracking=True)
    probability = Integer(string="Probability %")
    salesperson = Char(string="Salesperson")
    expected_close = Date(string="Expected close")
    next_contact_at = Datetime(string="Next contact")
    preferred_call_time = Time(string="Best time to call")
    active = Boolean(default=True)
    company_id = Many2one("res.company", ondelete="SET NULL")

    label = Char(compute="_compute_label", store=True, string="Label")

    @depends("stage", "priority")
    def _compute_label(self):
        _icons = {0: "○", 1: "●", 2: "★"}
        for r in self:
            icon = _icons.get(r.priority or 0, "●")
            r.label = f"{icon} {r.stage or 'new'}"
