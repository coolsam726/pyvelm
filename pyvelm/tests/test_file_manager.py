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
            browse={
                "folder_id": None,
                "breadcrumb": [],
                "folders": [
                    {"id": 5, "name": "Logos", "child_count": 0, "file_count": 2},
                ],
                "rows": [
                    {
                        "id": 1,
                        "name": "logo.png",
                        "mimetype": "image/png",
                        "size": 1024,
                        "thumbnail_url": "/api/attachment/1/download",
                    },
                ],
                "searching": False,
            },
            accept="image/*",
            q="",
            multi=False,
            can_upload=True,
        )
        self.assertIn("pvFilePicker", html)
        self.assertIn("data-pv-cfg", html)
        self.assertIn("JSON.parse($el.dataset.pvCfg)", html)
        self.assertIn("Upload", html)
        self.assertIn("onPickFiles", html)
        # Folder navigation + breadcrumb wiring is present.
        self.assertIn("navigate(", html)
        self.assertIn("All files", html)
        self.assertIn("goUp()", html)
        # The accept filter shows up so the operator knows what's allowed.
        self.assertIn("image/*", html)

    def test_picker_dialog_renders_empty_state(self):
        tpl = _env.get_template("widgets/file_picker.html")
        html = tpl.render(
            browse={
                "folder_id": None, "breadcrumb": [], "folders": [],
                "rows": [], "searching": False,
            },
            accept="", q="", multi=True, can_upload=False,
        )
        self.assertIn("This folder is empty", html)
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
        self.assertIn("window._pvFilePickerFieldCfg", html)
        self.assertIn("PvDialog.open", html)
        self.assertIn("logo_id", html)
        # Initial seed lands in the Alpine config payload.
        self.assertIn("old-logo.png", html)


class UploadPanelTemplateTests(unittest.TestCase):
    def test_upload_panel_targets_folder(self):
        tpl = _env.get_template("file_manager_upload_panel.html")
        html = tpl.render(
            folder_id=3,
            folder_label="Marketing",
            csrf_token="tok",
        )
        self.assertIn("pvFileUploadPanel", html)
        self.assertIn("data-pv-cfg", html)
        self.assertIn("Marketing", html)


class FileUrlWidgetTests(unittest.TestCase):
    """The Char-backed file_url widget (company branding logo / favicon)."""

    def test_renders_pick_button_and_value(self):
        from pyvelm.render import _render_file_url_widget

        html = str(_render_file_url_widget(
            "/api/attachment/9/download",
            {"name": "logo_url"},
            readonly=False,
        ))
        decoded = html.replace("&#34;", '"')
        self.assertIn("pvFileUrl", html)
        self.assertIn("data-pv-cfg", html)
        self.assertIn("Pick from library", html)
        # The hidden input binds via Alpine (:name/:value); the field
        # name + current URL ride in the per-element config payload.
        self.assertIn('"name": "logo_url"', decoded)
        self.assertIn("/api/attachment/9/download", decoded)
        # Default accept filter is image/*.
        self.assertIn('"accept": "image/*"', decoded)

    def test_readonly_hides_pick_button(self):
        from pyvelm.render import _render_file_url_widget

        html = str(_render_file_url_widget(
            "", {"name": "favicon_url"}, readonly=True,
        ))
        # Pick action is gated behind !readonly via x-if/x-show; the
        # config still flags readonly so the JS disables editing.
        self.assertIn('"readonly": true', html.replace("&#34;", '"'))

    def test_accept_override_from_widget_options(self):
        from pyvelm.render import _render_file_url_widget

        html = str(_render_file_url_widget(
            "",
            {"name": "doc_url", "widget_options": {"accept": "application/pdf"}},
            readonly=False,
        ))
        self.assertIn("application/pdf", html.replace("&#47;", "/"))


class LibraryShellTemplateTests(unittest.TestCase):
    """Smoke-tests for the new Drive-style library template."""

    def test_library_shell_renders_tree_action_bar_and_grid(self):
        tpl = _env.get_template("file_manager_library.html")
        html = tpl.render(
            active_folder_id=None,
            folder_tree=[
                {
                    "id": 1,
                    "name": "Marketing",
                    "parent_id": None,
                    "sequence": 10,
                    "color": "",
                    "child_count": 1,
                    "file_count": 0,
                },
                {
                    "id": 2,
                    "name": "Logos",
                    "parent_id": 1,
                    "sequence": 10,
                    "color": "",
                    "child_count": 0,
                    "file_count": 3,
                },
            ],
            unfiled_count=4,
            files=[
                {"id": 7, "name": "a.pdf", "mimetype": "application/pdf", "size": 2048, "thumbnail_url": "", "icon": "pdf"},
                {"id": 8, "name": "logo.png", "mimetype": "image/png", "size": 512, "thumbnail_url": "/api/attachment/8/download", "icon": "image"},
            ],
            visible_ids=[7, 8],
            searching=False,
            can_write=True,
            # Layout-side context the shell expects from merge_template_context.
            use_sidebar=True,
            breadcrumbs=[],
        )
        # Tree, action bar, selection wiring, and file area all land.
        self.assertIn("pvFileLibrary", html)
        self.assertIn("Marketing", html)
        self.assertIn("Logos", html)
        self.assertIn("Unfiled", html)
        self.assertIn("togglePublicSelected()", html)
        # Visible-id ordering is serialized to JS for shift-click range.
        self.assertIn("[7, 8]", html)
        # Config must not be inlined in x-data — Alpine breaks on ";".
        self.assertIn("window._pvFileLibraryCfg", html)
        self.assertIn('x-data="pvFileLibrary(window._pvFileLibraryCfg)"', html)
        self.assertIn("New subfolder", html)
        self.assertIn("openUploadDialog", html)
        self.assertIn("pvOpenFileLibraryUpload", html)
        self.assertIn("childFolders()", html)
        self.assertIn("breadcrumb()", html)
        self.assertIn("goUp()", html)
        # New polish: view switcher, three modes, collapse, copy/move.
        self.assertIn("setView('grid')", html)
        self.assertIn("setView('tiles')", html)
        self.assertIn("setView('details')", html)
        self.assertIn("toggleCollapse(", html)
        # Tree starts collapsed except the active working-directory path.
        self.assertIn("collapseAllbut(", html)
        self.assertIn("Move to", html)
        self.assertIn("Copy to", html)
        # Type-icon preview path for non-image rows.
        self.assertIn("fileIcon(file", html)
        # Small screens collapse every grid to a single column.
        self.assertIn("grid-cols-1 sm:grid-cols-[repeat(auto-fill", html)
        # Folder creation: a main-panel "New folder" affordance + a modal
        # dialog (no inline sidebar form, no window.prompt).
        self.assertIn("New folder", html)
        self.assertIn("submitNewFolder()", html)
        self.assertIn("Create folder", html)
        self.assertIn('x-show="creatingFolder"', html)

    def test_library_cfg_tolerates_semicolons_in_folder_names(self):
        tpl = _env.get_template("file_manager_library.html")
        html = tpl.render(
            active_folder_id=None,
            folder_tree=[
                {
                    "id": 1,
                    "name": "Sales; Marketing",
                    "parent_id": None,
                    "sequence": 10,
                    "color": "",
                    "child_count": 0,
                    "file_count": 0,
                },
            ],
            unfiled_count=0,
            files=[],
            visible_ids=[],
            searching=False,
            can_write=True,
            use_sidebar=True,
            breadcrumbs=[],
        )
        self.assertIn('x-data="pvFileLibrary(window._pvFileLibraryCfg)"', html)
        self.assertIn("Sales; Marketing", html)


class PropertiesTemplateTests(unittest.TestCase):
    """Properties template renders metadata + the dimensions row for images."""

    def _att(self, **overrides):
        defaults = dict(
            id=1,
            name="screenshot.png",
            datas_fname="screenshot.png",
            mimetype="image/png",
            file_size=10240,
            res_model="",
            res_id=0,
            type="binary",
            url="",
            storage_key="abc",
            public=False,
            created_at="2026-05-27 10:00",
            updated_at="2026-05-27 10:05",
            folder_id=None,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_image_shows_dimensions_and_preview(self):
        tpl = _env.get_template("file_manager_properties.html")
        html = tpl.render(
            att=self._att(),
            mimetype="image/png",
            is_image=True,
            extension="png",
            dimensions=(1024, 768),
            owner_url="",
            folder_chain=[],
            panel_only=True,
        )
        self.assertIn("screenshot.png", html)
        self.assertIn("1024 × 768 px", html)
        # Human-size filter formats 10240 bytes as 10.0 KB.
        self.assertIn("10.0 KB", html)
        self.assertIn("/api/attachment/1/download", html)

    def test_non_image_hides_dimensions_row(self):
        tpl = _env.get_template("file_manager_properties.html")
        html = tpl.render(
            att=self._att(
                name="report.pdf", datas_fname="report.pdf",
                mimetype="application/pdf",
            ),
            mimetype="application/pdf",
            is_image=False,
            extension="pdf",
            dimensions=None,
            owner_url="",
            folder_chain=[],
            panel_only=True,
        )
        self.assertNotIn("Dimensions", html)
        # Non-image fallback shows the extension badge.
        self.assertIn("pdf", html.lower())

    def test_folder_breadcrumb_renders_when_chain_set(self):
        tpl = _env.get_template("file_manager_properties.html")
        html = tpl.render(
            att=self._att(),
            mimetype="image/png",
            is_image=True,
            extension="png",
            dimensions=None,
            owner_url="",
            folder_chain=[{"id": 1, "name": "Marketing"}, {"id": 2, "name": "Logos"}],
            panel_only=False,
        )
        self.assertIn("Marketing", html)
        self.assertIn("Logos", html)
        self.assertIn("?folder_id=1", html)
        self.assertIn("?folder_id=2", html)


if __name__ == "__main__":
    unittest.main()
