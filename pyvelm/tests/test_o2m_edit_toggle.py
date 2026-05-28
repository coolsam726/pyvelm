"""One2many edit_toggle (dialog vs inline switch)."""

import unittest
from unittest.mock import patch

from markupsafe import Markup

from pyvelm.render import _render_o2m_edit_toggle


class O2mEditToggleTests(unittest.TestCase):
    def test_edit_toggle_renders_switch_and_inline_pane(self):
        spec = {
            "name": "line_ids",
            "_record": None,
            "_form_view_url": "/web/views/base/line.form",
            "edit_toggle": True,
            "widget": "dialog",
            "columns": ["name"],
        }
        with (
            patch(
                "pyvelm.render._render_o2m_table",
                return_value=Markup('<div data-pane="dialog"></div>'),
            ),
            patch(
                "pyvelm.render._edit_o2m_table",
                return_value=Markup('<div data-pv-o2m-root></div>'),
            ),
        ):
            html = str(
                _render_o2m_edit_toggle(None, spec, None, mode="edit"),
            )
        self.assertIn("data-pv-o2m-edit-toggle", html)
        self.assertIn("pvO2mEditToggle", html)
        self.assertIn("data-pv-o2m-root", html)
        self.assertIn("Inline grid", html)
        self.assertIn('data-pane="dialog"', html)
        self.assertIn('data-pane="inline"', html)
        self.assertIn('data-pane="dialog"', html)
        self.assertIn(":data-o2m-mode", html)


if __name__ == "__main__":
    unittest.main()
