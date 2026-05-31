"""Shared constants for the base module (import-safe — no model registration)."""

from pyvelm.fonts import UI_FONT_FAMILY_CHOICES

MENU_LAYOUT_CHOICES: list[tuple[str, str]] = [
    ("", "Default (env var)"),
    ("apps", "Apps — sidebar icons + top bar"),
    ("sidebar", "Sidebar — 3-level collapsible"),
]

# Re-export for modules that import from ``base.constants``.
FONT_FAMILY_CHOICES = UI_FONT_FAMILY_CHOICES
