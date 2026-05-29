"""Shared constants for the base module (import-safe — no model registration)."""

MENU_LAYOUT_CHOICES: list[tuple[str, str]] = [
    ("", "Default (env var)"),
    ("apps", "Apps — sidebar icons + top bar"),
    ("sidebar", "Sidebar — 3-level collapsible"),
]
