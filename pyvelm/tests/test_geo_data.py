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


class GeoInstallHookTests(unittest.TestCase):
    def test_install_grants_acl_only(self):
        import sys
        from unittest.mock import MagicMock, patch

        from pyvelm import BUILTIN_MODULE_ROOTS

        root = str(BUILTIN_MODULE_ROOTS[0])
        if root not in sys.path:
            sys.path.insert(0, root)
        from geo_data import hooks as geo_hooks  # noqa: E402

        env = MagicMock()
        with patch.object(geo_hooks, "_grant_acl") as grant:
            geo_hooks.install(env)
        grant.assert_called_once_with(env)

    def test_seed_reference_data_uses_geography_seeder(self):
        import sys
        from unittest.mock import MagicMock, patch

        from pyvelm import BUILTIN_MODULE_ROOTS

        root = str(BUILTIN_MODULE_ROOTS[0])
        if root not in sys.path:
            sys.path.insert(0, root)
        from geo_data import hooks as geo_hooks  # noqa: E402
        from geo_data.seeders import GeographyDatabaseSeeder  # noqa: E402

        env = MagicMock()
        counts = {"continents": 1, "countries": 2, "states": 3, "cities": 4}
        with patch.object(
            GeographyDatabaseSeeder, "run", return_value=counts
        ) as run:
            out = geo_hooks.seed_reference_data(env)
        run.assert_called_once_with(env)
        self.assertEqual(out, counts)

    def test_manifest_discovers_geography_seeder_from_package(self):
        from pathlib import Path

        from pyvelm import BUILTIN_MODULE_ROOTS
        from pyvelm.loader import _read_manifest

        root = BUILTIN_MODULE_ROOTS[0]
        spec = _read_manifest(Path(root) / "geo_data")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(
            spec.seeders,
            ["geo_data.seeders.geography:GeographyDatabaseSeeder"],
        )


if __name__ == "__main__":
    unittest.main()
