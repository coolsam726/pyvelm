"""Tests for ``pyvelm.scaffolder``."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyvelm.scaffolder import (
    _rename_dotfile,
    _substitute,
    echo_next_steps_for_init,
    echo_next_steps_for_new,
    find_modules_root,
    find_project_root,
    materialise,
    valid_name,
)


class ScaffolderTests(unittest.TestCase):
    def test_valid_name(self):
        self.assertTrue(valid_name("tasks"))
        self.assertFalse(valid_name("9bad"))
        self.assertFalse(valid_name(""))

    def test_rename_dotfile(self):
        self.assertEqual(_rename_dotfile("dotgitignore"), ".gitignore")
        self.assertEqual(_rename_dotfile("dotenv"), ".env")
        self.assertEqual(_rename_dotfile("dot2foo"), "dot2foo")

    def test_substitute_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            _substitute("hello {{ missing }}", {})

    def test_materialise_refuses_existing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            target.mkdir()
            with self.assertRaises(FileExistsError):
                materialise("module", target, variables={"name": "x"})

    def test_materialise_unknown_kind_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            with self.assertRaises(RuntimeError):
                materialise("no-such-scaffold-xyz", target, variables={"name": "x"})

    def test_module_scaffold_variables(self):
        from pyvelm.scaffolder import module_scaffold_variables

        self.assertEqual(
            module_scaffold_variables("partners"),
            {"name": "partners", "display_name": "Partners"},
        )

    def test_materialise_module_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo_mod"
            materialise(
                "module",
                target,
                variables={"name": "demo_mod", "display_name": "Demo Mod"},
            )
            self.assertTrue((target / "__pyvelm__.py").is_file())

    def test_find_project_and_modules_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyvelm.toml").write_text(
                'modules_root = "custom_modules"\n', encoding="utf-8"
            )
            self.assertEqual(find_project_root(root), root)
            mods = find_modules_root(root)
            self.assertEqual(mods, (root / "custom_modules").resolve())

    def test_find_modules_root_default_app_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyvelm.toml").write_text("# empty\n", encoding="utf-8")
            self.assertEqual(
                find_modules_root(root),
                (root / "app" / "modules").resolve(),
            )

    def test_echo_next_steps_print(self):
        with patch("pyvelm.scaffolder.print") as printed:
            echo_next_steps_for_new("tasks", Path("/mods"))
            echo_next_steps_for_init("myapp")
        self.assertEqual(printed.call_count, 2)
