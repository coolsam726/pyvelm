"""Tests for list view CSV/Excel import and export."""
from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Boolean, Char, Environment, Integer, Many2one, Registry
from pyvelm.importer import (
    ImportBatchError,
    build_row_vals,
    decode_import_payload,
    encode_import_payload,
    export_csv_bytes,
    export_list_data,
    filter_import_fields,
    import_rows,
    import_data_line_no,
    import_errors_by_line,
    failed_import_sheet,
    failed_import_xlsx_bytes,
    import_template_data_rows,
    import_template_fields_for_view,
    import_template_headers,
    import_template_xlsx_bytes,
    parse_include_data_query,
    list_importable_fields,
    mapping_from_form,
    m2o_import_hint,
    parse_fields_query,
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

    def test_encode_payload_serializes_dates(self):
        from datetime import datetime

        raw = encode_import_payload(
            ["When"],
            [[datetime(2024, 6, 1, 12, 30)]],
        )
        headers, rows = decode_import_payload(raw)
        self.assertEqual(headers, ["When"])
        self.assertEqual(rows[0][0], "2024-06-01 12:30:00")

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

    def test_build_row_vals_m2o_by_numeric_id(self):
        env = self._env()
        tag_cls = env.registry["test.import.tag"]
        tag_rs = MagicMock()
        tag_rs.id = 42
        with patch.object(tag_cls, "search", return_value=tag_rs):
            vals = build_row_vals(
                env,
                "test.import.item",
                ["42"],
                {0: "tag_id"},
            )
        self.assertEqual(vals["tag_id"], 42)

    def test_import_rows_update_by_id(self):
        env = self._env()
        cls = env.registry["test.import.item"]
        rec = MagicMock()
        written: list[dict] = []

        def fake_write(vals):
            written.append(vals)

        rec.write = fake_write
        with patch.object(cls, "search", return_value=rec):
            with patch.object(env, "transaction"):
                result = import_rows(
                    env,
                    "test.import.item",
                    [["1", "Updated"]],
                    {0: "id", 1: "name"},
                    update_by_id=True,
                )
        self.assertEqual(result["updated"], 1)
        self.assertEqual(written, [{"name": "Updated"}])

    def test_import_rows_atomic_aborts_on_any_error(self):
        env = self._env()
        cls = env.registry["test.import.item"]
        created: list[dict] = []

        def fake_create(vals):
            created.append(vals)
            return env["test.import.item"].browse(len(created))

        def fail_build_row_vals(*args, **kwargs):
            if len(created) >= 1:
                raise ValueError("bad row")
            return build_row_vals(*args, **kwargs)

        with patch.object(cls, "create", side_effect=fake_create):
            with patch(
                "pyvelm.importer.build_row_vals",
                side_effect=fail_build_row_vals,
            ):
                with patch.object(env, "transaction"):
                    with self.assertRaises(ImportBatchError) as ctx:
                        import_rows(
                            env,
                            "test.import.item",
                            [["Widget", "W1"], ["Bad", "B1"]],
                            {0: "name", 1: "code"},
                        )
        self.assertEqual(len(ctx.exception.result["errors"]), 1)
        self.assertEqual(ctx.exception.result["created"], 1)

    def test_import_rows_non_atomic_allows_partial_success(self):
        env = self._env()
        cls = env.registry["test.import.item"]
        created: list[dict] = []

        def fake_create(vals):
            created.append(vals)
            return env["test.import.item"].browse(len(created))

        def fail_build_row_vals(*args, **kwargs):
            if len(created) >= 1:
                raise ValueError("bad row")
            return build_row_vals(*args, **kwargs)

        with patch.object(cls, "create", side_effect=fake_create):
            with patch(
                "pyvelm.importer.build_row_vals",
                side_effect=fail_build_row_vals,
            ):
                with patch.object(env, "transaction"):
                    result = import_rows(
                        env,
                        "test.import.item",
                        [["Widget", "W1"], ["Bad", "B1"]],
                        {0: "name", 1: "code"},
                        atomic=False,
                    )
        self.assertEqual(result["created"], 1)
        self.assertEqual(len(result["errors"]), 1)


class ListIoActionsTests(unittest.TestCase):
    def test_default_actions_group_import_export_in_menu(self):
        env = MagicMock()
        env.has_access.side_effect = lambda _m, perm: perm in ("create", "read")
        view = MagicMock(module="demo", name="item.list", model="demo.item")
        acts = _default_list_io_actions(view, env, list_nav_query="search=foo")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["kind"], "menu")
        labels = [i["label"] for i in acts[0]["items"]]
        self.assertEqual(labels, ["Import", "Export CSV", "Export Excel"])
        self.assertTrue(acts[0]["items"][0]["url"].endswith("import?search=foo"))
        self.assertTrue(acts[0]["items"][1]["url"].endswith("export.csv?search=foo"))

    def test_merge_skips_duplicate_menu_items(self):
        declared = [{"label": "Import", "url": "/custom", "action_key": "import"}]
        defaults = _default_list_io_actions(
            MagicMock(module="demo", name="item.list", model="demo.item"),
            MagicMock(has_access=lambda *_a, **_k: True),
        )
        merged = _merge_list_page_actions(declared, defaults)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["url"], "/custom")
        self.assertEqual(merged[1]["kind"], "menu")
        menu_labels = [i["label"] for i in merged[1]["items"]]
        self.assertEqual(menu_labels, ["Export CSV", "Export Excel"])


class FailedImportExportTests(unittest.TestCase):
    def test_failed_import_sheet_appends_error_column(self):
        headers = ["Name", "Code"]
        rows = [["Good", "G1"], ["Bad", "B1"], ["Also bad", "B2"]]
        errors = [
            {"line": 3, "error": "Duplicate code"},
            {"line": 4, "error": "Missing parent"},
        ]
        out_headers, out_rows = failed_import_sheet(headers, rows, errors)
        self.assertEqual(out_headers, ["Name", "Code", "Error"])
        self.assertEqual(len(out_rows), 2)
        self.assertEqual(out_rows[0], ["Bad", "B1", "Duplicate code"])
        self.assertEqual(out_rows[1], ["Also bad", "B2", "Missing parent"])

    def test_failed_import_xlsx_bytes(self):
        data = failed_import_xlsx_bytes(
            ["Name"],
            [["Bad"]],
            [{"line": 2, "error": "Nope"}],
            title="Failed",
        )
        self.assertTrue(data[:2] == b"PK")


class ImportTestPreviewTests(unittest.TestCase):
    def test_import_data_line_no(self):
        self.assertEqual(import_data_line_no(0), 2)
        self.assertEqual(import_data_line_no(4), 6)

    def test_import_errors_by_line(self):
        errors = [
            {"line": 2, "error": "Missing name"},
            {"line": 5, "error": "Bad code"},
        ]
        self.assertEqual(
            import_errors_by_line(errors),
            {2: "Missing name", 5: "Bad code"},
        )
        self.assertEqual(import_errors_by_line(None), {})
        self.assertEqual(import_errors_by_line([]), {})


class ImportTemplateTests(unittest.TestCase):
    def test_filter_import_fields_respects_selection(self):
        fields = [
            {"name": "id", "label": "ID"},
            {"name": "name", "label": "Name"},
            {"name": "code", "label": "Code"},
        ]
        filtered = filter_import_fields(fields, ["name", "code"])
        self.assertEqual([f["name"] for f in filtered], ["name", "code"])

    def test_parse_fields_query(self):
        self.assertEqual(parse_fields_query(["name", "code"]), ["name", "code"])
        self.assertEqual(parse_fields_query("name,code"), ["name", "code"])

    def test_m2o_import_hint_mentions_code_for_country(self):
        env = MagicMock()
        env.registry = {"res.country": MagicMock(_fields={"name": 1, "code": 1})}
        hint = m2o_import_hint(env, "res.country")
        self.assertIn("code", hint)

    def test_import_template_fields_default_all_importable(self):
        env = MagicMock()
        env.registry = {"test.import.item": MagicMock(_fields={})}
        view = MagicMock()
        view.model = "test.import.item"
        fields = [
            {"name": "id", "label": "ID"},
            {"name": "name", "label": "Name"},
            {"name": "code", "label": "Reference"},
        ]
        with patch(
            "pyvelm.importer.list_importable_fields",
            return_value=fields,
        ):
            ordered = import_template_fields_for_view(env, view)
            self.assertEqual([f["name"] for f in ordered], ["id", "name", "code"])
            subset = import_template_fields_for_view(
                env, view, selected_names=["name"],
            )
            self.assertEqual([f["name"] for f in subset], ["name"])

    def test_import_template_xlsx_bytes(self):
        data = import_template_xlsx_bytes(["Name", "Email"], title="Partners")
        self.assertTrue(data[:2] == b"PK")

    def test_import_template_xlsx_bytes_with_rows(self):
        data = import_template_xlsx_bytes(
            ["Name"],
            rows=[["Alice"], ["Bob"]],
            title="Partners",
        )
        self.assertTrue(data[:2] == b"PK")
        self.assertGreater(len(data), 4000)

    def test_parse_include_data_query(self):
        self.assertFalse(parse_include_data_query(""))
        self.assertFalse(parse_include_data_query("0"))
        self.assertTrue(parse_include_data_query("1"))
        self.assertTrue(parse_include_data_query("true"))

    def test_import_template_data_rows(self):
        env = MagicMock()
        env.registry = {"test.import.item": MagicMock(_fields={"name": 1, "code": 1})}
        rec = MagicMock()
        rec.name = "Widget"
        rec.code = "W1"
        fields = [
            {"name": "name", "label": "Name"},
            {"name": "code", "label": "Reference"},
        ]
        rows = import_template_data_rows(
            env, "test.import.item", fields, [rec],
        )
        self.assertEqual(rows, [["Widget", "W1"]])

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
