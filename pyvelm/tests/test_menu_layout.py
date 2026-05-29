"""Unit tests for per-company navigation layout resolution."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pyvelm.menu import (
    menu_layout,
    normalize_menu_layout_slug,
    reset_request_menu_layout,
    resolve_menu_layout,
    set_request_menu_layout,
)

_MODULE_ROOT = Path(__file__).resolve().parent.parent / "modules"
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

from base.constants import MENU_LAYOUT_CHOICES  # noqa: E402


class NormalizeSlugTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(normalize_menu_layout_slug(""))
        self.assertIsNone(normalize_menu_layout_slug(None))
        self.assertIsNone(normalize_menu_layout_slug("   "))

    def test_valid_slugs(self):
        self.assertEqual(normalize_menu_layout_slug("apps"), "apps")
        self.assertEqual(normalize_menu_layout_slug("SIDEBAR"), "sidebar")

    def test_deprecated_odoo_alias(self):
        self.assertEqual(normalize_menu_layout_slug("odoo"), "apps")

    def test_unknown_slug_returns_none(self):
        self.assertIsNone(normalize_menu_layout_slug("tabs"))


class ResolveMenuLayoutTests(unittest.TestCase):
    def test_context_wins_over_env(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "sidebar"}):
            self.assertEqual(resolve_menu_layout(context_value="apps"), "apps")

    def test_env_used_when_context_empty(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "sidebar"}):
            self.assertEqual(resolve_menu_layout(context_value=""), "sidebar")

    def test_default_apps_when_both_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PYVELM_MENU_LAYOUT", None)
            self.assertEqual(resolve_menu_layout(context_value=None), "apps")

    def test_unknown_context_falls_through_to_env(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "sidebar"}):
            self.assertEqual(resolve_menu_layout(context_value="unknown"), "sidebar")


class RequestMenuLayoutTests(unittest.TestCase):
    def test_menu_layout_uses_contextvar(self):
        token = set_request_menu_layout("sidebar")
        try:
            self.assertEqual(menu_layout(), "sidebar")
        finally:
            reset_request_menu_layout(token)

    def test_contextvar_reset_restores_env_default(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "sidebar"}):
            token = set_request_menu_layout("apps")
            try:
                self.assertEqual(menu_layout(), "apps")
            finally:
                reset_request_menu_layout(token)
            self.assertEqual(menu_layout(), "sidebar")


class ConstantsTests(unittest.TestCase):
    def test_choices_include_env_default(self):
        slugs = {slug for slug, _label in MENU_LAYOUT_CHOICES}
        self.assertIn("", slugs)
        self.assertIn("apps", slugs)
        self.assertIn("sidebar", slugs)


if __name__ == "__main__":
    unittest.main()
