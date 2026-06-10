"""CRUD audit trail — ``ir.audit.log``."""
from __future__ import annotations

from pyvelm import Char, Integer, Many2one, Text, models


class AuditLog(models.Model):
    _name = "ir.audit.log"

    name = Char(required=True, string="Summary")
    model = Char(string="Model")
    res_id = Integer(string="Record ID")
    action = Char(required=True, string="Action")
    user_id = Many2one("res.users", string="User")
    company_id = Many2one("res.company", string="Company")
    old_values = Text(string="Old values")
    new_values = Text(string="New values")
    ip_address = Char(string="IP address")
    user_agent = Char(string="User agent")
