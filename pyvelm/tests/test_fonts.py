"""Tests for per-company Google Fonts typography."""

from __future__ import annotations

import os
import unittest

from pyvelm.branding import branding_context, default_brand_globals
from pyvelm.fonts import (
    DEFAULT_FONT_FAMILY,
    company_font_css,
    company_font_context,
    google_fonts_stylesheet_url,
    normalize_font_family,
    resolve_font_family,
)


class FontNormalizeTests(unittest.TestCase):
    def test_empty_and_default_return_blank(self):
        self.assertEqual(normalize_font_family(""), "")
        self.assertEqual(normalize_font_family(None), "")
        self.assertEqual(normalize_font_family("  "), "")
        self.assertEqual(normalize_font_family("Inter"), "")
        self.assertEqual(normalize_font_family("default"), "")

    def test_valid_google_font_names(self):
        from pyvelm.fonts import UI_FONT_FAMILIES

        for name in UI_FONT_FAMILIES:
            with self.subTest(name=name):
                self.assertEqual(normalize_font_family(name), name)
        self.assertEqual(normalize_font_family("Roboto"), "Roboto")
        self.assertEqual(normalize_font_family("Open Sans"), "Open Sans")
        self.assertEqual(normalize_font_family("Source Sans 3"), "Source Sans 3")

    def test_rejects_unsafe_characters(self):
        self.assertEqual(normalize_font_family("Roboto;"), "")
        self.assertEqual(normalize_font_family("A' B"), "")
        self.assertEqual(normalize_font_family("<script>"), "")


class FontUrlTests(unittest.TestCase):
    def test_google_fonts_url_encodes_spaces(self):
        url = google_fonts_stylesheet_url("Open Sans")
        self.assertIn("family=Open+Sans:wght@", url)
        self.assertTrue(url.startswith("https://fonts.googleapis.com/css2?"))

    def test_default_inter_url(self):
        url = google_fonts_stylesheet_url(DEFAULT_FONT_FAMILY)
        self.assertIn("family=Inter:wght@", url)


class FontCssTests(unittest.TestCase):
    def test_company_font_css_sets_variables(self):
        css = company_font_css("Roboto")
        self.assertIn("@layer theme", css)
        self.assertIn("--font-sans: 'Roboto', ui-sans-serif", css)
        self.assertIn("--default-font-family: 'Roboto', ui-sans-serif", css)
        self.assertIn("html, body", css)
        self.assertIn("font-family: 'Roboto', ui-sans-serif", css)

    def test_empty_family_emits_no_css(self):
        self.assertEqual(company_font_css(""), "")
        self.assertEqual(company_font_css("Inter"), "")


class FontChoicesTests(unittest.TestCase):
    def test_ui_font_family_choices_include_default(self):
        from pyvelm.fonts import UI_FONT_FAMILY_CHOICES, UI_FONT_FAMILIES

        self.assertEqual(UI_FONT_FAMILY_CHOICES[0], ("", "Default (Inter)"))
        choice_values = {v for v, _lbl in UI_FONT_FAMILY_CHOICES}
        for family in UI_FONT_FAMILIES:
            self.assertIn(family, choice_values)


class FontContextTests(unittest.TestCase):
    def test_default_context_uses_inter(self):
        ctx = company_font_context(None)
        self.assertEqual(ctx["company_font_family"], DEFAULT_FONT_FAMILY)
        self.assertIn("Inter", ctx["company_font_stylesheet_url"])
        self.assertEqual(ctx["company_font_style"], "")

    def test_env_override(self):
        os.environ["PYVELM_FONT_FAMILY"] = "Roboto"
        try:
            ctx = company_font_context(None)
            self.assertEqual(ctx["company_font_family"], "Roboto")
            self.assertIn("Roboto", ctx["company_font_stylesheet_url"])
            self.assertIn("'Roboto'", ctx["company_font_style"])
        finally:
            os.environ.pop("PYVELM_FONT_FAMILY", None)

    def test_resolve_font_family_priority(self):
        os.environ["PYVELM_FONT_FAMILY"] = "Lato"
        try:
            self.assertEqual(resolve_font_family(company_value="Roboto"), "Roboto")
            self.assertEqual(resolve_font_family(company_value=""), "Lato")
        finally:
            os.environ.pop("PYVELM_FONT_FAMILY", None)
        self.assertEqual(resolve_font_family(company_value=""), DEFAULT_FONT_FAMILY)


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
    def __init__(self, mgr, *, company_id=1, has_company_model=True, uid=None):
        self._mgr = mgr
        self.company_id = company_id
        self.uid = uid
        self.registry = {"res.company"} if has_company_model else set()

    def with_company(self, _cid):
        return _FakeEnvLevel(self._mgr)


class FontContextFromCompanyTests(unittest.TestCase):
    def test_company_font_overrides_env(self):
        os.environ["PYVELM_FONT_FAMILY"] = "Lato"
        try:
            co = _FakeCompany(font_family="Montserrat")
            env = _FakeEnv(_FakeCompanyManager(co))
            ctx = company_font_context(env, company_id=1)
            self.assertEqual(ctx["company_font_family"], "Montserrat")
            self.assertIn("Montserrat", ctx["company_font_stylesheet_url"])
            self.assertIn("'Montserrat'", ctx["company_font_style"])
        finally:
            os.environ.pop("PYVELM_FONT_FAMILY", None)


class BrandingFontIntegrationTests(unittest.TestCase):
    def test_branding_context_includes_font_keys(self):
        ctx = branding_context(None)
        self.assertIn("company_font_stylesheet_url", ctx)
        self.assertIn("company_font_style", ctx)
        self.assertIn("company_font_family", ctx)

    def test_default_brand_globals_include_font(self):
        g = default_brand_globals()
        self.assertIn("company_font_stylesheet_url", g)

    def test_head_theme_renders_font_css_without_escaping_quotes(self):
        import jinja2

        from pyvelm.fonts import company_font_css

        loader = jinja2.PackageLoader("pyvelm", "templates")
        env = jinja2.Environment(loader=loader, autoescape=True)
        template = env.get_template("layouts/_head_theme.html")
        css = company_font_css("Poppins")
        html = template.render(company_theme_style="", company_font_style=css)
        self.assertIn("font-family: 'Poppins'", html)
        self.assertNotIn("&#39;", html)


if __name__ == "__main__":
    unittest.main()
