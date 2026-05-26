"""Tests for the HTML sanitizer used by the ``Html`` field."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Html, Registry
from pyvelm.html_sanitizer import sanitize_html


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
