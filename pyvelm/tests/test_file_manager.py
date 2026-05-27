"""Tests for the file_manager kanban thumbnail slot + picker templates."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from pyvelm.render import _env, _kanban_cards_for_records


class KanbanImageSlotTests(unittest.TestCase):
    """The ``image`` card slot drops a URL onto each card dict."""

    def _records(self, *items):
        for item in items:
            yield SimpleNamespace(**item)

    def test_image_url_picked_from_attr(self):
        view = SimpleNamespace(module="file_manager", model="ir.attachment", name="x")
        recs = list(self._records(
            {"id": 1, "name": "a.png", "thumbnail_url": "/api/attachment/1/download"},
            {"id": 2, "name": "b.pdf", "thumbnail_url": ""},
        ))
        cards = _kanban_cards_for_records(
            recs,
            # Skip title/subtitle so we don't drag in the full BaseModel
            # rendering stack — the slot we're testing is image_url.
            title_attr=None,
            subtitle_attr=None,
            image_attr="thumbnail_url",
            fields_spec=[],
            badges_spec=[],
            form_view=None,
            view=view,
        )
        self.assertEqual(cards[0]["image_url"], "/api/attachment/1/download")
        self.assertEqual(cards[1]["image_url"], "")

    def test_missing_attr_yields_empty_url(self):
        view = SimpleNamespace(module="file_manager", model="ir.attachment", name="x")
        recs = list(self._records({"id": 1, "name": "foo"}))
        cards = _kanban_cards_for_records(
            recs,
            title_attr=None,
            subtitle_attr=None,
            image_attr="thumbnail_url",  # attr not present on record
            fields_spec=[],
            badges_spec=[],
            form_view=None,
            view=view,
        )
        self.assertEqual(cards[0]["image_url"], "")


class FilePickerTemplateTests(unittest.TestCase):
    """Templates parse and emit the expected hooks."""

    def test_picker_dialog_renders(self):
        tpl = _env.get_template("widgets/file_picker.html")
        html = tpl.render(
            rows=[
                {
                    "id": 1,
                    "name": "logo.png",
                    "mimetype": "image/png",
                    "size": 1024,
                    "thumbnail_url": "/api/attachment/1/download",
                },
            ],
            accept="image/*",
            q="",
            multi=False,
            can_upload=True,
        )
        self.assertIn("pvFilePicker", html)
        self.assertIn("Upload", html)
        self.assertIn("/web/files/picker/upload", html)
        # The accept filter shows up so the operator knows what's allowed.
        self.assertIn("image/*", html)

    def test_picker_dialog_renders_empty_state(self):
        tpl = _env.get_template("widgets/file_picker.html")
        html = tpl.render(
            rows=[], accept="", q="", multi=True, can_upload=False
        )
        self.assertIn("No files match", html)
        # Multi-mode footer shows up.
        self.assertIn("Use selected", html)

    def test_picker_field_renders_with_initial(self):
        tpl = _env.get_template("widgets/file_picker_field.html")
        html = tpl.render(
            name="logo_id",
            multi=False,
            readonly=False,
            accept="image/*",
            initial=[
                {
                    "id": 7,
                    "name": "old-logo.png",
                    "mimetype": "image/png",
                    "thumbnail_url": "/api/attachment/7/download",
                }
            ],
        )
        self.assertIn("pvFilePickerField", html)
        self.assertIn("logo_id", html)
        # Initial seed lands in the Alpine config payload.
        self.assertIn("old-logo.png", html)


if __name__ == "__main__":
    unittest.main()
