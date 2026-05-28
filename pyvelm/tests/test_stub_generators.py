"""Typing stub generation (``pyvelm make:stubs``)."""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from pyvelm.stub_generators import (
    discover_include_paths,
    ensure_pyrightconfig,
    generate_stubs,
    load_stub_index,
    write_pyrightconfig,
)


class StubGeneratorTests(unittest.TestCase):
    def _mini_project(self, tmp: Path) -> Path:
        root = tmp / "erp"
        root.mkdir()
        (root / "pyvelm.toml").write_text(
            'modules_root = "app/modules"\n', encoding="utf-8"
        )
        mod = root / "app" / "modules" / "demo"
        (mod / "models").mkdir(parents=True)
        (mod / "views").mkdir(parents=True)
        (mod / "__pyvelm__.py").write_text(
            textwrap.dedent(
                """
                NAME = "demo"
                VERSION = (0, 1, 0)
                DEPENDS: list[str] = []
                DATA: list[str] = ["views/item.py"]
                """
            ),
            encoding="utf-8",
        )
        (mod / "models" / "__init__.py").write_text(
            "from . import item  # noqa: F401\n", encoding="utf-8"
        )
        (mod / "models" / "item.py").write_text(
            textwrap.dedent(
                """
                from pyvelm import BaseModel, Char

                class Item(BaseModel):
                    _name = "demo.item"
                    name = Char()
                """
            ),
            encoding="utf-8",
        )
        (mod / "views" / "item.py").write_text(
            textwrap.dedent(
                """
                from pyvelm.builders import list_view

                VIEWS = [
                    list_view("item.list", "demo.item", fields=["name"]),
                ]
                """
            ),
            encoding="utf-8",
        )
        return root

    def test_load_stub_index_finds_model_and_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_project(Path(tmp))
            modules_root = root / "app" / "modules"
            _reg, _specs, index = load_stub_index(modules_root=modules_root)
            self.assertIn("demo.item", index.models)
            self.assertIn("demo.item.list", index.qualified_views)
            self.assertEqual(index.view_models.get("demo.item.list"), "demo.item")

    def test_discover_include_paths_finds_examples_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / "examples" / "modules").mkdir(parents=True)
            includes = discover_include_paths(root)
            self.assertIn("examples/modules", includes)

    def test_write_pyrightconfig_refreshes_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "examples" / "modules").mkdir(parents=True)
            (root / "pyrightconfig.json").write_text(
                '{"include": ["app"], "stubPath": "old"}', encoding="utf-8"
            )
            stubs = root / ".pyvelm" / "typing"
            stubs.mkdir(parents=True)
            self.assertTrue(write_pyrightconfig(root, stubs_dir=stubs))
            cfg = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
            self.assertIn("examples/modules", cfg["include"])
            self.assertEqual(cfg["stubPath"], ".pyvelm/typing")

    def test_ensure_pyrightconfig_creates_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_project(Path(tmp))
            out = root / ".pyvelm" / "typing"
            out.mkdir(parents=True)
            self.assertTrue(ensure_pyrightconfig(root, stubs_dir=out))
            cfg = root / "pyrightconfig.json"
            self.assertTrue(cfg.is_file())
            text = cfg.read_text(encoding="utf-8")
            self.assertIn(".pyvelm/typing", text)
            self.assertFalse(ensure_pyrightconfig(root, stubs_dir=out))

    def test_generate_stubs_writes_pyvelm_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_project(Path(tmp))
            modules_root = root / "app" / "modules"
            out = root / ".pyvelm" / "typing"
            written, index = generate_stubs(
                out, modules_root=modules_root, include_bundled=False
            )
            self.assertTrue((written / "py.typed").is_file())
            self.assertTrue((written / "names.pyi").is_file())
            self.assertTrue((written / "pyvelm" / "env.pyi").is_file())
            names = (written / "names.pyi").read_text(encoding="utf-8")
            self.assertIn('"demo.item"', names)
            self.assertIn('"demo.item.list"', names)
            env_stub = (written / "pyvelm" / "env.pyi").read_text(encoding="utf-8")
            self.assertIn("ModelName", env_stub)
            fields_stub = (written / "pyvelm" / "fields.pyi").read_text(encoding="utf-8")
            self.assertIn("comodel_name: ModelName", fields_stub)
            self.assertGreater(len(index.models), 0)


if __name__ == "__main__":
    unittest.main()
