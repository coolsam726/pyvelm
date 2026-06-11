"""Tests for list view CSV/Excel import and export."""
from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Boolean, Char, Environment, Integer, Many2one, Registry
from pyvelm.importer import (
    build_row_vals,
    decode_import_payload,
    encode_import_payload,
    export_csv_bytes,
    export_list_data,
    import_rows,
    import_template_fields_for_view,
    import_template_headers,
    import_template_xlsx_bytes,
    list_importable_fields,
    mapping_from_form,
    parse_tabular_upload,
    suggest_column_mapping,
)
from pyvelm.render import _default_list_io_actions, _merge_list_page_actions


class ImporterMappingTests(unittest.TestCase):
    def test_suggest_mapping_matches_name_and_label(self):
        fields = [
            {"name": "code", "label": "Reference"},
            {"name": "name", "label": "Name"},
        ]
        headers = ["Reference", "name"]
        mapping = suggest_column_mapping(headers, fields)
        self.assertEqual(mapping[0], "code")
        self.assertEqual(mapping[1], "name")


class ImporterParseTests(unittest.TestCase):
    def test_parse_csv(self):
        content = b"name,code\nAlice,A1\nBob,B2\n"
        headers, rows = parse_tabular_upload(content, "partners.csv")
        self.assertEqual(headers, ["name", "code"])
        self.assertEqual(rows[0], ["Alice", "A1"])

    def test_roundtrip_payload(self):
        headers = ["name"]
        rows = [["A"], ["B"]]
        raw = encode_import_payload(headers, rows)
        h2, r2 = decode_import_payload(raw)
        self.assertEqual(h2, headers)
        self.assertEqual(r2, rows)


class ImporterModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = Registry()
        with cls.reg.activate():

            class Tag(BaseModel):
                _name = "test.import.tag"
                name = Char(required=True)

            class Item(BaseModel):
                _name = "test.import.item"
                name = Char(required=True)
                code = Char()
                active = Boolean(default=True)
                tag_id = Many2one("test.import.tag")

        cls.reg = cls.reg

    def _env(self):
        env = Environment(None, registry=self.reg, uid=1)
        env.has_access = lambda _m, _p: True  # type: ignore[method-assign]
        env.check_access = lambda *_a, **_k: None  # type: ignore[method-assign]
        return env

    def test_list_importable_fields_skips_readonly(self):
        env = self._env()
        fields = list_importable_fields(env, "test.import.item")
        names = {f["name"] for f in fields}
        self.assertIn("name", names)
        self.assertIn("code", names)
        self.assertIn("id", names)

    def test_import_rows_create(self):
        env = self._env()
        cls = env.registry["test.import.item"]
        created: list[dict] = []

        def fake_create(vals):
            created.append(vals)
            return env["test.import.item"].browse(len(created))

        with patch.object(cls, "create", side_effect=fake_create):
            with patch.object(env, "transaction"):
                result = import_rows(
                    env,
                    "test.import.item",
                    [["Widget", "W1"], ["Gadget", "G1"]],
                    {0: "name", 1: "code"},
                )
        self.assertEqual(result["created"], 2)
        self.assertEqual(len(created), 2)

    def test_build_row_vals_m2o_by_name(self):
        env = self._env()
        tag_cls = env.registry["test.import.tag"]
        tag_rs = MagicMock()
        tag_rs.id = 5
        with patch.object(tag_cls, "search", return_value=tag_rs):
            vals = build_row_vals(
                env,
                "test.import.item",
                ["My Tag", "X"],
                {0: "tag_id", 1: "code"},
            )
        self.assertEqual(vals["tag_id"], 5)
        self.assertEqual(vals["code"], "X")


class ListIoActionsTests(unittest.TestCase):
    def test_default_actions_include_import_export(self):
        env = MagicMock()
        env.has_access.side_effect = lambda _m, perm: perm in ("create", "read")
        view = MagicMock(module="demo", name="item.list", model="demo.item")
        acts = _default_list_io_actions(view, env, list_nav_query="search=foo")
        labels = [a["label"] for a in acts]
        self.assertIn("Import", labels)
        self.assertIn("Export CSV", labels)
        self.assertTrue(acts[1]["url"].endswith("export.csv?search=foo"))

    def test_merge_skips_duplicates(self):
        declared = [{"label": "Import", "url": "/custom"}]
        defaults = [{"label": "Import", "url": "/built-in"}]
        merged = _merge_list_page_actions(declared, defaults)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "/custom")


class ImportTemplateTests(unittest.TestCase):
    def test_import_template_fields_follow_list_columns(self):
        env = MagicMock()
        env.registry = {"test.import.item": MagicMock(_fields={})}
        view = MagicMock()
        view.model = "test.import.item"
        fields = [
            {"name": "id", "label": "ID"},
            {"name": "name", "label": "Name"},
            {"name": "code", "label": "Reference"},
        ]
        arch = {"fields": [{"name": "name"}, {"name": "code"}]}
        with patch(
            "pyvelm.importer.list_importable_fields",
            return_value=fields,
        ), patch("pyvelm.views.resolve_arch", return_value=arch):
            ordered = import_template_fields_for_view(env, view)
        self.assertEqual([f["name"] for f in ordered], ["id", "name", "code"])

    def test_import_template_xlsx_bytes(self):
        data = import_template_xlsx_bytes(["Name", "Email"], title="Partners")
        self.assertTrue(data[:2] == b"PK")

    def test_import_template_headers_use_labels(self):
        fields = [
            {"name": "code", "label": "Reference"},
            {"name": "name", "label": "Name"},
        ]
        self.assertEqual(
            import_template_headers(fields),
            ["Reference", "Name"],
        )

    def test_mapping_from_form_reads_selects(self):
        fields = [{"name": "name", "label": "Name"}]
        form = {"map_0": "name"}
        mapping = mapping_from_form(form, ["Name"], fields)
        self.assertEqual(mapping[0], "name")


class ExportBytesTests(unittest.TestCase):
    def test_export_csv_bytes(self):
        data = export_csv_bytes(["Name"], [["Alice"]])
        self.assertIn(b"Name", data)
        self.assertIn(b"Alice", data)
