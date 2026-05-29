"""Unit tests for document_layout HTML assembly (no database required)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from markupsafe import Markup

from document_layout.constants import DOCUMENT_LAYOUT_CHOICES
from document_layout.layout import (
    _apply_overrides,
    _jinja_env,
    _render_inline,
    _render_sample,
    _sample_body,
    paper_content_min_height,
    paper_css_size,
    render_designer,
    tint_color,
)


def _ctx(*, layout: str = "light", accent: str = "#714B67", **extra) -> dict:
    pw, ph = paper_css_size("A4")
    base = {
        "name": "Acme Corporation",
        "address_lines": ["77 Santa Barbara Rd", "Pleasant Hill CA 94523", "VAT: US12345671"],
        "logo_url": "",
        "accent": accent,
        "secondary": accent,
        "font": "",
        "font_face_css": Markup(""),
        "copyright": "© Acme Corporation",
        "layout": layout,
        "paper": "A4",
        "paper_width": pw,
        "paper_height": ph,
        "paper_content_min": paper_content_min_height("A4"),
        "folder_tint": tint_color(accent),
        "vat": "US12345671",
    }
    base.update(extra)
    return base


class PaperSizeTests(unittest.TestCase):
    def test_a4_dimensions(self):
        self.assertEqual(paper_css_size("A4"), ("210mm", "297mm"))

    def test_letter_dimensions(self):
        w, h = paper_css_size("Letter")
        self.assertEqual(w, "215.9mm")
        self.assertEqual(h, "279.4mm")

    def test_unknown_paper_falls_back_to_a4(self):
        self.assertEqual(paper_css_size("Tabloid"), paper_css_size("A4"))

    def test_content_min_height_matches_margins(self):
        self.assertEqual(paper_content_min_height("A4"), "265mm")
        self.assertEqual(paper_content_min_height("Letter"), "247.4mm")


class TintColorTests(unittest.TestCase):
    def test_tint_is_mostly_white(self):
        tinted = tint_color("#714B67")
        self.assertTrue(tinted.startswith("#"))
        r = int(tinted[1:3], 16)
        g = int(tinted[3:5], 16)
        b = int(tinted[5:7], 16)
        self.assertGreater(r, 240)
        self.assertGreater(g, 240)
        self.assertGreater(b, 240)

    def test_short_hex_supported(self):
        self.assertEqual(len(tint_color("#abc")), 7)


class ApplyOverridesTests(unittest.TestCase):
    def test_layout_override(self):
        ctx = _apply_overrides(MagicMock(), _ctx(), {"layout": "folder"})
        self.assertEqual(ctx["layout"], "folder")

    def test_color_override_recomputes_folder_tint(self):
        ctx = _apply_overrides(MagicMock(), _ctx(), {"color": "#0000ff"})
        self.assertEqual(ctx["accent"], "#0000ff")
        self.assertEqual(ctx["folder_tint"], tint_color("#0000ff"))

    def test_paper_override_updates_sizes(self):
        ctx = _apply_overrides(MagicMock(), _ctx(), {"paper": "Letter"})
        self.assertEqual(ctx["paper_width"], "215.9mm")
        self.assertEqual(ctx["paper_content_min"], "247.4mm")


class LayoutChoiceTests(unittest.TestCase):
    def test_all_layouts_registered(self):
        slugs = {slug for slug, _ in DOCUMENT_LAYOUT_CHOICES}
        expected = {
            "light", "boxed", "bold", "striped", "editorial", "split", "dark", "folder",
        }
        self.assertEqual(slugs, expected)


class ExternalLayoutRenderTests(unittest.TestCase):
    LAYOUT_MARKERS = {
        "light": "table.doc-header",
        "boxed": "layout-boxed",
        "bold": "layout-bold",
        "striped": "layout-striped",
        "editorial": "layout-editorial",
        "split": "doc-frame-split",
        "dark": "layout-dark",
        "folder": "folder-header",
    }

    def test_each_layout_renders_preview_html(self):
        tpl = _jinja_env().get_template("external_layout.html")
        body = _sample_body(_ctx())
        for layout, marker in self.LAYOUT_MARKERS.items():
            with self.subTest(layout=layout):
                html = tpl.render(
                    body=body,
                    company=_ctx(layout=layout),
                    title="Invoice",
                    preview=True,
                )
                self.assertIn(marker, html)
                self.assertIn("doc-frame", html)
                self.assertIn("© Acme Corporation", html)

    def test_pdf_path_uses_doc_frame_min_height(self):
        html = _jinja_env().get_template("external_layout.html").render(
            body=_sample_body(_ctx()),
            company=_ctx(),
            title="Invoice",
            preview=False,
        )
        self.assertIn("min-height: 265mm", html)
        self.assertNotIn('class="sheet"', html)


class InlinePreviewRenderTests(unittest.TestCase):
    def test_inline_preview_scoped_under_pvdoc(self):
        html = _render_inline(_ctx(layout="light"))
        self.assertIn("pvdoc-sheet", html)
        self.assertIn("class=\"pvdoc layout-light\"", html)

    def test_sample_body_includes_doc_number(self):
        html = str(_sample_body(_ctx()))
        self.assertIn('class="doc-number"', html)
        self.assertIn("INV/2026/00001", html)

    def test_folder_inline_has_tab_shape_and_company_in_strip(self):
        html = _render_inline(_ctx(layout="folder"))
        self.assertIn("folder-company-info", html)
        self.assertIn("folder-tab-row", html)
        self.assertIn("M5.70364 48", html)
        self.assertIn("Sample Invoice", html)
        self.assertIn("Acme Corporation", html)
        self.assertIn("doc-number", html)

    def test_folder_hides_duplicate_doc_title_in_body(self):
        html = _render_inline(_ctx(layout="folder"))
        self.assertIn(".layout-folder main .doc-title", html)


class FooterLayoutTests(unittest.TestCase):
    def test_footer_pinned_with_doc_frame(self):
        html = _render_sample(_ctx(layout="light"))
        self.assertIn("doc-footer", html)
        self.assertIn("position: absolute", html)
        self.assertIn("padding-bottom: 40px", html)

    def test_split_puts_copyright_in_sidebar(self):
        html = _render_sample(_ctx(layout="split"))
        self.assertIn("split-footer", html)
        self.assertIn("© Acme Corporation", html)


class DesignerTemplateTests(unittest.TestCase):
    def test_designer_dialog_lists_every_layout_choice(self):
        company = MagicMock()
        company.id = 1
        company.name = "Acme"
        company.document_layout = "light"
        company.paper_format = "A4"
        company.primary_color = "#714B67"
        company.secondary_color = "#714B67"
        company.google_font = ""
        company.logo_url = ""

        Company = MagicMock()
        Company.search.return_value = company
        Company.browse.return_value = company

        env = MagicMock()
        env.__getitem__ = MagicMock(return_value=Company)

        html = render_designer(env, company_id=1, csrf_token="tok")
        for slug, label in DOCUMENT_LAYOUT_CHOICES:
            short = label.split(" — ", 1)[0]
            with self.subTest(slug=slug):
                self.assertIn(f'value="{slug}"', html)
                self.assertIn(short, html)


if __name__ == "__main__":
    unittest.main()
