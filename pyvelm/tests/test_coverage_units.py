"""Unit tests for modules with little or no HTTP/DB coverage."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm.console import parse_signature
from pyvelm.file_icons import file_icon_key
from pyvelm.geo_utils import flag_emoji, geo_packages_available, require_geo_packages
from pyvelm.reports.compile import ColumnMeta
from pyvelm.reports.execute import ReportResult
from pyvelm.reports.export_pdf import export_pdf
from pyvelm.reports.export_xlsx import export_xlsx
from pyvelm.reports.secure import search_read
from pyvelm.server import apply_runtime_env, default_serve_env
from pyvelm.storage import (
    DbStorageBackend,
    LocalStorageBackend,
    get_backend,
    reset_backend_cache,
)
from pyvelm.workflow import runtime as workflow_runtime


class ConsoleSignatureTests(unittest.TestCase):
    def test_parse_signature_options_and_args(self):
        name, parts = parse_signature(
            "make:module {name} {--force} {--tag=default : help text}"
        )
        self.assertEqual(name, "make:module")
        self.assertEqual(len(parts), 3)
        self.assertFalse(parts[0].is_option)
        self.assertEqual(parts[0].dest, "name")
        self.assertTrue(parts[1].flag)
        self.assertEqual(parts[2].dest, "tag")
        self.assertEqual(parts[2].default, "default")


class ReportExportTests(unittest.TestCase):
    def _sample_result(self) -> ReportResult:
        cols = [
            ColumnMeta(key="name", label="Name", expr="name"),
            ColumnMeta(key="amount", label="Amount", expr="amount"),
        ]
        rows = [{"name": "Alice", "amount": 10}, {"name": "Bob", "amount": 20}]
        return ReportResult(columns=cols, rows=rows, row_count=2, duration_ms=1)

    def test_export_pdf_bytes(self):
        data = export_pdf(self._sample_result(), title="Test")
        self.assertTrue(data.startswith(b"%PDF"))

    def test_export_xlsx_bytes(self):
        data = export_xlsx(self._sample_result(), title="Test")
        self.assertTrue(data[:2] == b"PK")

    def test_search_read_empty(self):
        env = MagicMock()
        Model = MagicMock()
        Model.search.return_value = []
        env.__getitem__.return_value = Model
        self.assertEqual(search_read(env, "res.partner"), [])


class StorageTests(unittest.TestCase):
    def tearDown(self):
        reset_backend_cache()

    def test_local_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalStorageBackend(root=tmp)
            key = backend.save("hello.txt", b"hello")
            self.assertEqual(backend.load(key), b"hello")
            backend.delete(key)

    def test_db_backend(self):
        b = DbStorageBackend()
        self.assertEqual(b.save("x", b"x"), "")
        with self.assertRaises(RuntimeError):
            b.load("")

    def test_get_backend_local(self):
        with patch.dict(os.environ, {"PYVELM_ATTACHMENT_BACKEND": "local"}, clear=False):
            reset_backend_cache()
            b = get_backend()
            self.assertIsInstance(b, LocalStorageBackend)


class ServerHelperTests(unittest.TestCase):
    def test_apply_runtime_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_ENV", None)
            env = apply_runtime_env("development")
            self.assertEqual(env, "development")
            self.assertEqual(os.environ.get("PYVELM_ENV"), "development")

    def test_default_serve_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_ENV", None)
            self.assertEqual(default_serve_env(from_cli=True), "development")


class FileIconTests(unittest.TestCase):
    def test_pdf_mimetype(self):
        self.assertEqual(file_icon_key("application/pdf"), "pdf")

    def test_image_mimetype(self):
        self.assertEqual(file_icon_key("image/png"), "image")

    def test_extension_fallback(self):
        self.assertEqual(file_icon_key("application/octet-stream", "report.pdf"), "pdf")

    def test_unknown(self):
        self.assertEqual(file_icon_key(None, "data.bin"), "file")


class GeoUtilsTests(unittest.TestCase):
    def test_flag_emoji(self):
        self.assertEqual(flag_emoji("FR"), "🇫🇷")
        self.assertEqual(flag_emoji("X"), "")
        self.assertEqual(flag_emoji("FRA"), "")
        self.assertEqual(flag_emoji(None), "")

    def test_geo_packages_available(self):
        self.assertIsInstance(geo_packages_available(), bool)

    def test_require_geo_packages_ok_or_raises(self):
        if geo_packages_available():
            require_geo_packages()
        else:
            with self.assertRaises(RuntimeError):
                require_geo_packages()


class ConsoleSignatureTestsExtra(unittest.TestCase):
    def test_empty_signature_raises(self):
        with self.assertRaises(ValueError):
            parse_signature("   ")


class WorkflowRuntimeTests(unittest.TestCase):
    def test_maybe_auto_start_no_schema(self):
        env = MagicMock()
        env.registry = {}
        env._acl_bypass = False
        record = MagicMock()
        record._name = "res.partner"
        workflow_runtime.maybe_auto_start_workflow(env, record)

    def test_maybe_auto_start_bypass(self):
        env = MagicMock()
        env._acl_bypass = True
        workflow_runtime.maybe_auto_start_workflow(env, MagicMock())
