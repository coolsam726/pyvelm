"""Shared constants for the base module (import-safe — no model registration)."""

MENU_LAYOUT_CHOICES: list[tuple[str, str]] = [
    ("", "Default (env var)"),
    ("apps", "Apps — sidebar icons + top bar"),
    ("sidebar", "Sidebar — 3-level collapsible"),
]

# Popular Google Fonts — value is the exact family name on fonts.google.com.
FONT_FAMILY_CHOICES: list[tuple[str, str]] = [
    ("", "Default (Inter)"),
    ("Inter", "Inter"),
    ("Roboto", "Roboto"),
    ("Open Sans", "Open Sans"),
    ("Lato", "Lato"),
    ("Montserrat", "Montserrat"),
    ("Source Sans 3", "Source Sans 3"),
    ("Nunito", "Nunito"),
    ("Poppins", "Poppins"),
    ("Raleway", "Raleway"),
    ("Merriweather", "Merriweather"),
    ("Playfair Display", "Playfair Display"),
    ("Oswald", "Oswald"),
    ("Work Sans", "Work Sans"),
]
