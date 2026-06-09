"""Tests for fluent ``Manifest`` builder and manifest loading."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from pyvelm import loader
from pyvelm.manifest import Manifest, bump_version_in_manifest_text


class ManifestBuilderTests(unittest.TestCase):
    def test_fluent_to_dict(self):
        m = (
            Manifest.make("partners")
            .version(0, 4, 0)
            .depends("base")
            .data("views/partner.py", "views/menu.py")
            .install_hook("partners.hooks:install")
            .summary("Partners")
            .category("Business")
            .catalog_access("res.users", "read", policy="view_any")
        )
        d = m.to_dict()
        self.assertEqual(d["NAME"], "partners")
        self.assertEqual(d["VERSION"], (0, 4, 0))
        self.assertEqual(d["DEPENDS"], ["base"])
        self.assertEqual(d["DATA"], ["views/partner.py", "views/menu.py"])
        self.assertEqual(d["INSTALL_HOOK"], "partners.hooks:install")
        self.assertEqual(d["CATALOG_ACCESS_POLICY"], "view_any")

    def test_version_requires_segment(self):
        with self.assertRaises(ValueError):
            Manifest.make("x").to_dict()

    def test_bump_version_legacy_and_fluent(self):
        legacy = 'VERSION = (0, 1, 0)\n'
        self.assertIn(
            "(0, 2, 0)",
            bump_version_in_manifest_text(legacy, (0, 1, 0), (0, 2, 0)) or "",
        )
        fluent = 'manifest = Manifest.make("x").version(0, 1, 0)\n'
        bumped = bump_version_in_manifest_text(fluent, (0, 1, 0), (0, 2, 0))
        self.assertIn(".version(0, 2, 0)", bumped or "")


class ManifestLoaderTests(unittest.TestCase):
    def _write_manifest(self, root: Path, name: str, body: str) -> Path:
        mod = root / name
        mod.mkdir(parents=True)
        (mod / "__init__.py").write_text("", encoding="utf-8")
        (mod / "__pyvelm__.py").write_text(textwrap.dedent(body), encoding="utf-8")
        return mod

    def test_read_fluent_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_manifest(
                root,
                "fluent_mod",
                """
                from pyvelm.manifest import Manifest

                manifest = (
                    Manifest.make("fluent_mod")
                    .version(1, 2, 3)
                    .depends("base")
                    .data("views/menu.py")
                    .summary("Fluent")
                )
                """,
            )
            specs = loader.discover([root])
            spec = specs["fluent_mod"]
            self.assertEqual(spec.version, (1, 2, 3))
            self.assertEqual(spec.depends, ["base"])
            self.assertEqual(spec.data, ["views/menu.py"])
            self.assertEqual(spec.summary, "Fluent")

    def test_read_legacy_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_manifest(
                root,
                "legacy_mod",
                """
                NAME = "legacy_mod"
                VERSION = (0, 9, 0)
                DEPENDS = []
                DATA = []
                SUMMARY = "Legacy"
                """,
            )
            specs = loader.discover([root])
            spec = specs["legacy_mod"]
            self.assertEqual(spec.version, (0, 9, 0))
            self.assertEqual(spec.summary, "Legacy")

    def test_missing_manifest_keys_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_manifest(
                root,
                "bad",
                """
                from pyvelm.manifest import Manifest
                manifest = Manifest.make("bad")
                """,
            )
            with self.assertRaises(ValueError):
                loader.discover([root])
