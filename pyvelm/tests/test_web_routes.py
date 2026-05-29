"""Tests for manifest WEB_ROUTES registration."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pyvelm.loader import _read_manifest, register_web_routes


class WebRoutesManifestTests(unittest.TestCase):
    def test_manifest_reads_web_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "demo"
            pkg.mkdir()
            (pkg / "__pyvelm__.py").write_text(
                'NAME = "demo"\n'
                'VERSION = (0, 1, 0)\n'
                'WEB_ROUTES = "demo.web:register_routes"\n',
                encoding="utf-8",
            )
            spec = _read_manifest(pkg)
            self.assertIsNotNone(spec)
            assert spec is not None
            self.assertEqual(spec.web_routes, "demo.web:register_routes")

    def test_register_web_routes_calls_registrar(self):
        called: list = []

        def fake_register(app):
            called.append(app)

        import sys
        import types

        mod = types.ModuleType("demo.web")
        mod.register_routes = fake_register
        sys.modules["demo.web"] = mod
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                pkg = root / "demo"
                pkg.mkdir()
                (pkg / "__pyvelm__.py").write_text(
                    'NAME = "demo"\n'
                    'VERSION = (0, 1, 0)\n'
                    'WEB_ROUTES = "demo.web:register_routes"\n',
                    encoding="utf-8",
                )
                app = MagicMock()
                register_web_routes(app, [root])
        finally:
            sys.modules.pop("demo.web", None)

        self.assertEqual(len(called), 1)
        self.assertIs(called[0], app)


if __name__ == "__main__":
    unittest.main()
