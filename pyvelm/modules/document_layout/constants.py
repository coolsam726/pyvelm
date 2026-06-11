"""Shared constants for document layout (import-safe — no model registration)."""

DOCUMENT_LAYOUT_CHOICES = [
    ("light",     "Light"),
    ("boxed",     "Boxed"),
    ("bold",      "Bold"),
    ("striped",   "Striped"),
    ("bubble",    "Bubble — Odoo 19"),
    ("wave",      "Wave — Odoo 19"),
    ("folder",    "Folder — Odoo 19"),
    # Legacy layouts (still render for existing companies)
    ("editorial", "Editorial (legacy)"),
    ("split",     "Split (legacy)"),
    ("dark",      "Dark (legacy)"),
]

GOOGLE_FONTS = [
    "Inter", "Roboto", "Open Sans", "Lato", "Montserrat",
    "Poppins", "Merriweather", "Nunito", "Source Sans 3",
]
GOOGLE_FONT_CHOICES = [("", "Default (DejaVu Sans)")] + [(f, f) for f in GOOGLE_FONTS]
