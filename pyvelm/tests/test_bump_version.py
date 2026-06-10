"""Release version bump script (``scripts/bump_version.py``)."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_bump_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BumpVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bump = _load_bump_module()

    def test_parse_version_accepts_semver(self):
        self.assertEqual(self.bump.parse_version("1.4.0"), "1.4.0")

    def test_parse_version_rejects_invalid(self):
        with self.assertRaises(ValueError):
            self.bump.parse_version("v1.4.0")
        with self.assertRaises(ValueError):
            self.bump.parse_version("1.4")

    def test_finalize_changelog_moves_unreleased(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changelog = root / "CHANGELOG.md"
            changelog.write_text(
                "## Unreleased\n\n### Added\n\n- **Feature** — detail.\n\n"
                "## [1.0.0] — 2026-01-01\n\n### Added\n\n- Old.\n",
                encoding="utf-8",
            )
            self.bump.finalize_changelog(changelog, "1.1.0", "2026-06-01")
            text = changelog.read_text(encoding="utf-8")
            self.assertIn("## Unreleased\n\n## [1.1.0] — 2026-06-01", text)
            self.assertIn("**Feature**", text)
            self.assertIn("## [1.0.0] — 2026-01-01", text)
            self.assertNotIn("## Unreleased\n\n### Added", text)

    def test_finalize_changelog_rejects_empty_unreleased(self):
        with tempfile.TemporaryDirectory() as tmp:
            changelog = Path(tmp) / "CHANGELOG.md"
            changelog.write_text(
                "## Unreleased\n\n## [1.0.0] — 2026-01-01\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                self.bump.finalize_changelog(changelog, "1.1.0", "2026-06-01")

    def test_bump_pyproject_and_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pyproject = root / "pyproject.toml"
            pyproject.write_text('version = "1.0.0"\n', encoding="utf-8")
            init_pkg = root / "pyvelm"
            init_pkg.mkdir()
            init_file = init_pkg / "__init__.py"
            init_file.write_text('__version__ = "1.0.0"\n', encoding="utf-8")

            self.bump.bump_pyproject(pyproject, "1.2.0")
            self.bump.bump_init(init_file, "1.2.0")
            self.assertIn('version = "1.2.0"', pyproject.read_text(encoding="utf-8"))
            self.assertIn('__version__ = "1.2.0"', init_file.read_text(encoding="utf-8"))
            self.assertEqual(self.bump.read_pyproject_version(root), "1.2.0")
            self.assertEqual(self.bump.read_init_version(root), "1.2.0")
            self.assertEqual(self.bump.check_versions(root), [])

    def test_check_versions_detects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('version = "1.3.0"\n', encoding="utf-8")
            pkg = root / "pyvelm"
            pkg.mkdir()
            (pkg / "__init__.py").write_text('__version__ = "1.2.0"\n', encoding="utf-8")
            errors = self.bump.check_versions(root)
            self.assertEqual(len(errors), 1)
            self.assertIn("1.3.0", errors[0])
            self.assertIn("1.2.0", errors[0])


if __name__ == "__main__":
    unittest.main()
