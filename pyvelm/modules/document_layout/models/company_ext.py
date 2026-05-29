"""Document-layout config + contact block on `res.company` (via `_inherit`).

Drives the PDF document header (logo, name, address) and the chosen external
layout variant / paper format.
"""
from __future__ import annotations

from pyvelm import BaseModel, Char, depends

from ..constants import DOCUMENT_LAYOUT_CHOICES, GOOGLE_FONT_CHOICES, GOOGLE_FONTS

__all__ = [
    "DOCUMENT_LAYOUT_CHOICES",
    "GOOGLE_FONT_CHOICES",
    "GOOGLE_FONTS",
    "ResCompanyDocumentLayout",
]


class ResCompanyDocumentLayout(BaseModel):
    _inherit = "res.company"

    document_layout = Char(
        default="light", string="Document Layout",
        choices=DOCUMENT_LAYOUT_CHOICES,
    )
    paper_format = Char(
        default="A4", string="Paper Format",
        choices=[("A4", "A4"), ("Letter", "US Letter")],
    )
    secondary_color = Char(string="Secondary color")
    google_font = Char(string="Google Font", choices=GOOGLE_FONT_CHOICES)
    # Pseudo-field that hosts the "Design layout" dialog button (see widgets.py).
    document_designer = Char(
        compute="_compute_document_designer", store=False, string="Designer",
    )

    @depends("name")
    def _compute_document_designer(self):
        for r in self:
            r.document_designer = ""

    # Contact block for document headers (res.company has no address fields).
    street = Char(string="Street")
    city = Char(string="City")
    zip = Char(string="ZIP")
    phone = Char(string="Phone")
    email = Char(string="Email")
    vat = Char(string="Tax ID / VAT")
    website = Char(string="Website")

    def _address_lines(self) -> list[str]:
        """Ordered, non-empty header lines for this company."""
        self.ensure_one()
        city_zip = " ".join(p for p in (self.zip, self.city) if p)
        parts = [
            self.street, city_zip,
            self.email, self.phone, self.website,
            f"VAT: {self.vat}" if self.vat else None,
        ]
        return [p for p in parts if p]
