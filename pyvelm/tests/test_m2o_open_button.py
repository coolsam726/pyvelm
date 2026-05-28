"""Many2one display: label + dialog open button (not a full-cell link)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.render import _render_m2o, _render_m2o_open_button


class M2oOpenButtonTests(unittest.TestCase):
    def test_open_button_uses_dialog_trigger(self):
        html = str(_render_m2o_open_button("/web/views/geo_data/geo_data.country.form/record/1"))
        self.assertIn("data-pv-dialog", html)
        self.assertIn("data-pv-dialog-url=", html)
        self.assertNotIn("<a ", html)
        self.assertIn("stopPropagation", html)

    def test_display_m2o_label_not_wrapped_in_link(self):
        rec = MagicMock()
        rec._ids = (42,)
        spec = {"_form_view_url": "/web/views/base/partner.form"}
        with patch("pyvelm.web._display_value", return_value="Acme Corp"):
            html = str(_render_m2o(rec, spec, None))
        self.assertIn("Acme Corp", html)
        self.assertIn("pv-m2o-open", html)
        self.assertIn("data-pv-dialog", html)
        self.assertNotIn('class="inline-flex items-center gap-1 group/m2o', html)


if __name__ == "__main__":
    unittest.main()
