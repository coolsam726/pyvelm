"""Success toast payload after form save."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from pyvelm.web import _form_save_toast_headers, _form_save_toast_payload


class FormSaveToastTests(unittest.TestCase):
    def test_save_payload_includes_label(self):
        rec = MagicMock()
        with patch("pyvelm.web._display_value", return_value="Kenya"):
            payload = _form_save_toast_payload(rec)
        self.assertEqual(payload["variant"], "success")
        self.assertIn("Kenya", payload["message"])
        self.assertEqual(payload["title"], "Saved")

    def test_create_payload(self):
        rec = MagicMock()
        with patch("pyvelm.web._display_value", return_value="New lead"):
            payload = _form_save_toast_payload(rec, created=True)
        self.assertEqual(payload["title"], "Created")
        self.assertIn("New lead", payload["message"])

    def test_headers_json(self):
        rec = MagicMock()
        with patch("pyvelm.web._display_value", return_value="X"):
            headers = _form_save_toast_headers(rec)
        data = json.loads(headers["HX-Trigger"])
        self.assertIn("pv-toast", data)
        self.assertEqual(data["pv-toast"]["variant"], "success")


if __name__ == "__main__":
    unittest.main()
