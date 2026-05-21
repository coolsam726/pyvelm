"""res.company — the company/tenant model.

Each record represents an independent company. Users and partners carry
a Many2one to their "home" company; the Environment's company_id scopes
searches automatically when set.

Note: company_id is added directly to res.users in security.py (same
module) and to res.partner in the partners module (which depends on base
and thus loads res.company first).
"""
from __future__ import annotations

from pyvelm import BaseModel, Boolean, Char, Many2one


class Company(BaseModel):
    _name = "res.company"

    name = Char(required=True)
    active = Boolean(default=True)
    # Each company has a "home" currency. Monetary fields (slice C)
    # default to their record's company's currency. ON DELETE SET NULL
    # so deleting a currency doesn't cascade-delete the company.
    currency_id = Many2one("res.currency", ondelete="SET NULL")
