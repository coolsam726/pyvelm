"""User lifecycle events — ``ir.user.lifecycle``."""
from __future__ import annotations

from pyvelm import Char, Many2one, Text, models


class UserLifecycle(models.Model):
    _name = "ir.user.lifecycle"

    user_id = Many2one("res.users", required=True, string="User")
    event = Char(required=True, string="Event")
    detail = Text(string="Detail")
    actor_id = Many2one("res.users", string="Actor")
