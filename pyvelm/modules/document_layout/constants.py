"""Shared constants for document layout (import-safe — no model registration)."""

DOCUMENT_LAYOUT_CHOICES = [
    ("light",     "Light — clean header, white"),
    ("boxed",     "Boxed — framed company block"),
    ("bold",      "Bold — accent company header"),
    ("striped",   "Striped — alternating rows"),
    ("editorial", "Editorial — large title, minimal header"),
    ("split",     "Split — accent sidebar + white body"),
    ("dark",      "Dark — black header band"),
    ("folder",    "Folder — Odoo 19 tab header"),
]

GOOGLE_FONTS = [
    "Inter", "Roboto", "Open Sans", "Lato", "Montserrat",
    "Poppins", "Merriweather", "Nunito", "Source Sans 3",
]
GOOGLE_FONT_CHOICES = [("", "Default (DejaVu Sans)")] + [(f, f) for f in GOOGLE_FONTS]
