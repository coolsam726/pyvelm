"""White-label branding context."""
from __future__ import annotations

import os
import unittest

from pyvelm.branding import brand_dict, branding_context


class BrandingTests(unittest.TestCase):
    def test_defaults_without_env(self):
        brand = brand_dict(None)
        self.assertEqual(brand["app_name"], "pyvelm")
        self.assertFalse(brand["has_logo"])
        self.assertTrue(brand["show_powered_by"])

    def test_env_overrides(self):
        os.environ["PYVELM_APP_NAME"] = "Acme ERP"
        os.environ["PYVELM_LOGO_URL"] = "/logo-light.png"
        os.environ["PYVELM_COPYRIGHT"] = "© Acme 2026"
        os.environ["PYVELM_SHOW_POWERED_BY"] = "0"
        try:
            brand = brand_dict(None)
            self.assertEqual(brand["app_name"], "Acme ERP")
            self.assertTrue(brand["has_logo"])
            self.assertEqual(brand["logo_url_dark"], "/logo-light.png")
            self.assertEqual(brand["copyright"], "© Acme 2026")
            self.assertFalse(brand["show_powered_by"])
        finally:
            for key in (
                "PYVELM_APP_NAME",
                "PYVELM_LOGO_URL",
                "PYVELM_COPYRIGHT",
                "PYVELM_SHOW_POWERED_BY",
            ):
                os.environ.pop(key, None)

    def test_dark_logo_falls_back_to_light(self):
        os.environ["PYVELM_LOGO_URL"] = "/light.svg"
        try:
            brand = brand_dict(None)
            self.assertEqual(brand["logo_url_light"], "/light.svg")
            self.assertEqual(brand["logo_url_dark"], "/light.svg")
        finally:
            os.environ.pop("PYVELM_LOGO_URL", None)

    def test_dark_logo_env_override(self):
        os.environ["PYVELM_LOGO_URL"] = "/light.svg"
        os.environ["PYVELM_LOGO_URL_DARK"] = "/dark.svg"
        try:
            brand = brand_dict(None)
            self.assertEqual(brand["logo_url_dark"], "/dark.svg")
        finally:
            os.environ.pop("PYVELM_LOGO_URL", None)
            os.environ.pop("PYVELM_LOGO_URL_DARK", None)

    def test_branding_context_includes_theme(self):
        ctx = branding_context(None)
        self.assertIn("brand", ctx)
        self.assertIn("company_theme_style", ctx)
        self.assertEqual(ctx["brand"]["app_name"], "pyvelm")


if __name__ == "__main__":
    unittest.main()
