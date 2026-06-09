"""Outermost extension: ``self.super().button_cancel()`` (Odoo-style alias)."""
from __future__ import annotations

from pyvelm import models


class DemoOrderExtB(models.Model):
    _inherit = "super_chain.order"

    def button_cancel(self) -> dict:
        # Uses self.super() — equivalent to super().button_cancel() here.
        res = self.super().button_cancel()
        res["layers"] = [*res["layers"], "ext_b"]
        return res
