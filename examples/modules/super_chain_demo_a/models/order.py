"""Middle extension: ``super().button_cancel()`` then append audit note."""
from __future__ import annotations

from pyvelm import BaseModel, Char


class DemoOrderExtA(BaseModel):
    _inherit = "super_chain.order"

    cancel_note = Char(string="Cancel note")

    def button_cancel(self) -> dict:
        res = super().button_cancel()
        self.write({"cancel_note": "cancelled via ext_a"})
        res["layers"] = [*res["layers"], "ext_a"]
        return res
