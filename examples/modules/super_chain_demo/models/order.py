"""Base ``super_chain.order`` — root of the ``button_cancel`` super() chain."""
from __future__ import annotations

from pyvelm import Char, models


class DemoOrder(models.Model):
    _name = "super_chain.order"

    name = Char(required=True, string="Reference")
    state = Char(default="draft", string="Status")

    def button_cancel(self) -> dict:
        """Cancel the order (Odoo-style action button hook)."""
        self.ensure_one()
        self.write({"state": "cancelled"})
        return {"state": "cancelled", "layers": ["base"]}
