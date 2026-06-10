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
from pyvelm.tests._isolation import purge_import_prefix


class StubGeneratorTests(unittest.TestCase):
    def setUp(self):
        purge_import_prefix("demo")

    def tearDown(self):
        purge_import_prefix("demo")

    def _mini_project(self, tmp: Path) -> Path:
        root = tmp / "erp"
        root.mkdir()
        (root / "pyvelm.toml").write_text(
            'modules_root = "app/modules"\n', encoding="utf-8"
        )
        mod = root / "app" / "modules" / "demo"
        mod.mkdir(parents=True)
        (mod / "__init__.py").write_text("", encoding="utf-8")
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
            self.assertIn("def query(self, model_name: ModelName) -> Query", env_stub)
            models_stub = (written / "models_stubs.pyi").read_text(encoding="utf-8")
            self.assertIn("def query(self) -> Query", models_stub)
            fields_stub = (written / "pyvelm" / "fields.pyi").read_text(encoding="utf-8")
            self.assertIn("comodel_name: ModelName", fields_stub)
            self.assertIn("OrmFieldBuilder", fields_stub)
            menus_stub = written / "pyvelm" / "builders" / "menus.pyi"
            self.assertTrue(menus_stub.is_file())
            self.assertNotIn("Field", menus_stub.read_text(encoding="utf-8"))
            self.assertFalse((written / "pyvelm" / "builders.pyi").exists())
            self.assertFalse((written / "pyvelm" / "builders" / "__init__.pyi").exists())
            self.assertGreater(len(index.models), 0)

    def test_default_stubs_dir(self):
        from pyvelm.stub_generators import default_stubs_dir

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertTrue(str(default_stubs_dir(root)).endswith(".pyvelm/typing"))

    def test_discover_include_paths_defaults_to_dot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "pyvelm.toml").write_text('modules_root = "/abs/outside"\n', encoding="utf-8")
            includes = discover_include_paths(root)
            self.assertEqual(includes, [])

    def test_discover_include_paths_pyvelm_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "erp"
            root.mkdir()
            mods = root / "custom" / "modules"
            mods.mkdir(parents=True)
            (root / "pyvelm.toml").write_text('modules_root = "custom/modules"\n', encoding="utf-8")
            includes = discover_include_paths(root)
            self.assertIn("custom/modules", includes)

    def test_write_pyrightconfig_outside_stub_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            stubs = Path("/tmp/outside-stubs")
            stubs.mkdir(exist_ok=True)
            self.assertTrue(write_pyrightconfig(root, stubs_dir=stubs))
            cfg = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
            self.assertIn(str(stubs.resolve()), cfg["stubPath"])

    def test_write_pyrightconfig_invalid_json_and_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "pyrightconfig.json").write_text("{bad", encoding="utf-8")
            stubs = root / ".pyvelm" / "typing"
            stubs.mkdir(parents=True)
            self.assertTrue(write_pyrightconfig(root, stubs_dir=stubs))
            desired = {
                "include": discover_include_paths(root),
                "stubPath": ".pyvelm/typing",
                "extraPaths": [".pyvelm/typing"],
                "pythonVersion": "3.10",
                "typeCheckingMode": "basic",
            }
            cfg = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
            for key, val in desired.items():
                self.assertEqual(cfg[key], val)
            self.assertFalse(write_pyrightconfig(root, stubs_dir=stubs))

    def test_default_pyrightconfig_variables(self):
        from pyvelm.stub_generators import default_pyrightconfig_variables

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vars_ = default_pyrightconfig_variables(root)
            self.assertIn("include_json", vars_)

    def test_load_stub_index_view_inherits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_project(Path(tmp))
            modules_root = root / "app" / "modules"
            (modules_root / "demo" / "views" / "item.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.builders import list_view

                    VIEWS = [
                        list_view("item.list", "demo.item", fields=["name"]),
                    ]
                    VIEW_INHERITS = [
                        {"name": "item.list.ext", "inherit": "demo.item.list", "operations": []},
                    ]
                    """
                ),
                encoding="utf-8",
            )
            _reg, _specs, index = load_stub_index(modules_root=modules_root)
            self.assertIn("demo.item.list.ext", index.qualified_views)

    def test_generate_stubs_removes_legacy_builders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._mini_project(Path(tmp))
            modules_root = root / "app" / "modules"
            out = root / ".pyvelm" / "typing"
            legacy = out / "pyvelm" / "builders.pyi"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text("old", encoding="utf-8")
            (legacy.parent / "builders" / "__init__.pyi").parent.mkdir(parents=True, exist_ok=True)
            (legacy.parent / "builders" / "__init__.pyi").write_text("old", encoding="utf-8")
            generate_stubs(out, modules_root=modules_root, include_bundled=False)
            self.assertFalse(legacy.exists())
            self.assertFalse((legacy.parent / "builders" / "__init__.pyi").exists())

    def test_literal_union_helpers(self):
        from pyvelm.stub_generators import (
            _escape_literal,
            _literal_members,
            _literal_union,
        )

        empty = _literal_union("M", [])
        self.assertIn("nothing discovered", empty)
        big = _literal_union("M", [f"m{i}" for i in range(500)])
        self.assertIn("truncated", big)
        self.assertIn(_escape_literal('a"b'), _literal_members(['a"b']))


if __name__ == "__main__":
    unittest.main()
