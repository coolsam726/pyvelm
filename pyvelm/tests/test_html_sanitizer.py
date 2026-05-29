"""Tests for the HTML sanitizer used by the ``Html`` field."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Html, Registry
from pyvelm.html_sanitizer import _safe_url, _scheme_of, sanitize_html


class SanitizerTests(unittest.TestCase):
    def test_strips_script_tag_and_body(self):
        out = sanitize_html(
            "<p>ok</p><script>alert('x')</script><p>after</p>"
        )
        self.assertEqual(out, "<p>ok</p><p>after</p>")

    def test_strips_event_attributes(self):
        out = sanitize_html('<a href="https://x" onclick="hack()">link</a>')
        self.assertIn('href="https://x"', out)
        self.assertNotIn("onclick", out)

    def test_blocks_javascript_url(self):
        out = sanitize_html('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript:", out)
        # The tag survives without an href.
        self.assertIn("<a", out)

    def test_allows_safe_email_html(self):
        src = (
            '<p><strong>Hello</strong> world</p>'
            '<ul><li>a</li><li>b</li></ul>'
            '<a href="https://example.com">link</a>'
        )
        self.assertEqual(sanitize_html(src), src)

    def test_drops_iframe(self):
        out = sanitize_html('<p>before</p><iframe src="https://evil"></iframe>after')
        self.assertNotIn("<iframe", out)
        self.assertIn("<p>before</p>", out)
        self.assertIn("after", out)

    def test_keeps_safe_style(self):
        out = sanitize_html('<p style="color: red">x</p>')
        self.assertIn('style="color: red"', out)

    def test_drops_dangerous_style(self):
        out = sanitize_html(
            '<p style="background: url(javascript:alert(1))">x</p>'
        )
        self.assertNotIn("javascript", out)
        # The tag itself stays.
        self.assertIn("<p", out)

    def test_empty_and_none(self):
        self.assertEqual(sanitize_html(""), "")
        self.assertEqual(sanitize_html(None), "")

    def test_keeps_mark_for_highlight(self):
        out = sanitize_html('<p>see <mark>this</mark></p>')
        self.assertIn("<mark>", out)

    def test_keeps_data_attrs_for_task_list(self):
        out = sanitize_html(
            '<ul data-type="taskList">'
            '<li data-checked="true">'
            '<label><input type="checkbox" checked></label>'
            '<div>do it</div></li></ul>'
        )
        self.assertIn('data-type="taskList"', out)
        self.assertIn('data-checked="true"', out)
        self.assertIn('<input type="checkbox"', out)
        self.assertIn("do it", out)

    def test_drops_non_checkbox_inputs(self):
        out = sanitize_html('<p>x</p><input type="text" name="evil">')
        self.assertNotIn("<input", out)
        self.assertIn("<p>x</p>", out)

    def test_keeps_text_align_style(self):
        out = sanitize_html('<p style="text-align: center">hi</p>')
        self.assertIn("text-align", out)

    def test_keeps_color_style(self):
        out = sanitize_html('<p><span style="color: #ff0066">bold</span></p>')
        self.assertIn('style="color: #ff0066"', out)


class SanitizerBranchTests(unittest.TestCase):
    """Targets the remaining edge branches in the parser/helpers."""

    def test_scheme_of_empty(self):
        self.assertEqual(_scheme_of(""), "")
        self.assertEqual(_scheme_of("no-scheme/here"), "")

    def test_safe_url_none_and_blank(self):
        self.assertIsNone(_safe_url(None))
        self.assertIsNone(_safe_url("   "))

    def test_blank_href_dropped(self):
        out = sanitize_html('<a href="   ">x</a>')
        self.assertNotIn("href", out)
        self.assertIn("<a>x</a>", out)

    def test_blank_style_dropped(self):
        out = sanitize_html('<p style="">x</p>')
        self.assertEqual(out, "<p>x</p>")

    def test_style_empty_and_unbalanced_declarations_dropped(self):
        # First decl is kept; the empty one is skipped; the unbalanced
        # paren decl is dropped, leaving only the safe property.
        out = sanitize_html('<p style="color: red; ; width: calc(100% ">x</p>')
        self.assertIn("color: red", out)
        self.assertNotIn("calc", out)

    def test_disallowed_attribute_dropped(self):
        out = sanitize_html('<p foo="bar">x</p>')
        self.assertEqual(out, "<p>x</p>")

    def test_img_src_kept(self):
        out = sanitize_html('<img src="https://x/y.png" alt="a">')
        self.assertIn('src="https://x/y.png"', out)

    def test_unknown_tag_stripped_keeps_text(self):
        out = sanitize_html("<font>hi</font>")
        self.assertEqual(out, "hi")

    def test_contents_inside_script_fully_dropped(self):
        # <script>/<style> bodies are CDATA in HTMLParser (one data event).
        out = sanitize_html("<script>var x=1<2;</script>tail")
        self.assertEqual(out, "tail")

    def test_contents_inside_iframe_fully_dropped(self):
        # iframe is parsed normally, so nested start/end tags, entity refs
        # and char refs each fire their callback while _drop_depth > 0.
        out = sanitize_html("<iframe><b>x</b>&amp;&#65;</iframe>tail")
        self.assertEqual(out, "tail")

    def test_self_closing_variants(self):
        self.assertEqual(sanitize_html("<br/>"), "<br />")
        self.assertIn("<img", sanitize_html('<img src="https://x" alt="a"/>'))
        self.assertEqual(sanitize_html("<font/>after"), "after")   # not allowed
        self.assertEqual(sanitize_html("<script/>x"), "x")         # drop tag
        self.assertEqual(sanitize_html('<input type="text"/>'), "")  # guarded type

    def test_unclosed_unknown_end_tag_stripped(self):
        out = sanitize_html("<p>x</p></font>")
        self.assertEqual(out, "<p>x</p>")

    def test_entity_and_charref_preserved_outside_drop(self):
        out = sanitize_html("Tom &amp; Jerry &#169;")
        self.assertEqual(out, "Tom &amp; Jerry &#169;")

    def test_comment_pi_and_decl_discarded(self):
        out = sanitize_html("<!-- c --><?xml v?><p>keep</p><!DOCTYPE html>")
        self.assertEqual(out, "<p>keep</p>")


class HtmlFieldTests(unittest.TestCase):
    def test_field_to_python_sanitizes(self):
        reg = Registry()
        with reg.activate():

            class Article(BaseModel):
                _name = "test.html.article"
                body = Html()

        cls = reg["test.html.article"]
        field = cls._fields["body"]
        self.assertEqual(
            field.to_python("<p>ok</p><script>bad()</script>"),
            "<p>ok</p>",
        )
        self.assertEqual(field.to_sql_param(""), None)
        self.assertEqual(field.to_python(None), None)


if __name__ == "__main__":
    unittest.main()
