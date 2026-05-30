"""White-label branding context."""
from __future__ import annotations

import os
import unittest

from pyvelm.branding import brand_dict, branding_context, default_brand_globals


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
        self.assertIn("company_font_stylesheet_url", ctx)
        self.assertEqual(ctx["brand"]["app_name"], "pyvelm")

    def test_default_brand_globals(self):
        g = default_brand_globals()
        self.assertEqual(g["brand"]["app_name"], "pyvelm")
        self.assertEqual(g["company_primary_color"], "")
        self.assertEqual(g["company_theme_style"], "")


class _FakeCompany:
    def __init__(self, **vals):
        self._vals = vals

    def ensure_one(self):
        return self

    def __getattr__(self, name):
        return self.__dict__["_vals"].get(name)


class _FakeCompanyManager:
    def __init__(self, co, *, exists=True):
        self._co = co
        self._exists = exists

    def search(self, _domain):
        return [self._co] if self._exists else []

    def browse(self, _cid):
        return self._co


class _FakeEnvLevel:
    def __init__(self, mgr):
        self._mgr = mgr

    def sudo(self):
        return self

    def __getitem__(self, _model):
        return self._mgr


class _FakeEnv:
    def __init__(self, mgr, *, company_id=1, has_company_model=True):
        self._mgr = mgr
        self.company_id = company_id
        self.registry = {"res.company"} if has_company_model else set()

    def with_company(self, _cid):
        return _FakeEnvLevel(self._mgr)


class BrandingFromCompanyTests(unittest.TestCase):
    """Company-row values win over env/defaults (the ``env`` path)."""

    def test_company_values_take_priority(self):
        co = _FakeCompany(
            app_name="Co Name",
            app_tagline="Co tagline",
            logo_url="/co-light.png",
            logo_url_dark="",  # falls back to light
            favicon_url="/co.ico",
            copyright_text="© Co",
            support_email="help@co",
            support_url="https://co/help",
            show_powered_by=False,
        )
        env = _FakeEnv(_FakeCompanyManager(co))
        brand = brand_dict(env, company_id=1)
        self.assertEqual(brand["app_name"], "Co Name")
        self.assertEqual(brand["tagline"], "Co tagline")
        self.assertEqual(brand["logo_url_light"], "/co-light.png")
        self.assertEqual(brand["logo_url_dark"], "/co-light.png")
        self.assertEqual(brand["favicon_url"], "/co.ico")
        self.assertFalse(brand["show_powered_by"])  # bool(co value)

    def test_company_id_resolved_from_env_when_omitted(self):
        co = _FakeCompany(app_name="EnvCo", show_powered_by=True)
        env = _FakeEnv(_FakeCompanyManager(co), company_id=7)
        brand = brand_dict(env)  # company_id falls back to env.company_id
        self.assertEqual(brand["app_name"], "EnvCo")

    def test_missing_company_row_falls_back_to_defaults(self):
        co = _FakeCompany(app_name="Ignored")
        env = _FakeEnv(_FakeCompanyManager(co, exists=False))
        brand = brand_dict(env, company_id=99)
        self.assertEqual(brand["app_name"], "pyvelm")

    def test_no_company_model_in_registry_falls_back(self):
        env = _FakeEnv(_FakeCompanyManager(_FakeCompany()), has_company_model=False)
        brand = brand_dict(env, company_id=1)
        self.assertEqual(brand["app_name"], "pyvelm")

    def test_none_company_id_skips_company_lookup(self):
        env = _FakeEnv(_FakeCompanyManager(_FakeCompany()), company_id=None)
        brand = brand_dict(env)  # cid resolves to None → no company branding
        self.assertEqual(brand["app_name"], "pyvelm")


if __name__ == "__main__":
    unittest.main()
