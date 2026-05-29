"""Unit tests for the geo_data seed helpers (flag emoji + pure logic)."""
from __future__ import annotations

import builtins
import unittest
from unittest.mock import patch


from pyvelm import geo_utils
from pyvelm.geo_utils import (
    flag_emoji,
    geo_packages_available,
    require_geo_packages,
)


class FlagEmojiTests(unittest.TestCase):
    """``flag_emoji`` builds the regional-indicator emoji from ISO 3166-1."""

    def test_us(self):
        # U + S → 0x1F1FA + 0x1F1F8
        self.assertEqual(flag_emoji("US"), "\U0001F1FA\U0001F1F8")

    def test_lowercase_is_normalised(self):
        self.assertEqual(flag_emoji("us"), flag_emoji("US"))

    def test_empty_or_invalid_returns_blank(self):
        self.assertEqual(flag_emoji(""), "")
        self.assertEqual(flag_emoji(None), "")
        self.assertEqual(flag_emoji("USA"), "")  # too long
        self.assertEqual(flag_emoji("U1"), "")   # non-alpha


class GeoPackageAvailabilityTests(unittest.TestCase):
    """``require_geo_packages`` raises a helpful message when the extras
    aren't installed; importing the helper should not crash even when
    the extras are present."""

    def test_helper_returns_bool(self):
        self.assertIsInstance(geo_packages_available(), bool)

    def test_require_succeeds_or_mentions_extras(self):
        try:
            require_geo_packages()
        except RuntimeError as exc:
            self.assertIn("pyvelm[geo]", str(exc))

    def test_available_false_when_import_fails(self):
        real_import = builtins.__import__

        def _boom(name, *args, **kwargs):
            if name in ("geonamescache", "pycountry"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", _boom):
            self.assertFalse(geo_packages_available())

    def test_require_raises_when_unavailable(self):
        with patch.object(geo_utils, "geo_packages_available", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                require_geo_packages()
        self.assertIn("pyvelm[geo]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
