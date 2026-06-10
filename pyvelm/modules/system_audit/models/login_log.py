"""Login / logout / failure history — ``ir.login.log``."""
from __future__ import annotations

from pyvelm import Char, Integer, Many2one, models


class LoginLog(models.Model):
    _name = "ir.login.log"

    user_id = Many2one("res.users", string="User")
    email = Char(string="Email")
    event = Char(required=True, string="Event")
    ip_address = Char(string="IP address")
    user_agent = Char(string="User agent")
    session_id = Char(string="Session")
    session_lifetime_minutes = Integer(string="Session lifetime (min)")
