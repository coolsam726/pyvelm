"""Typing stub generation (``pyvelm make:stubs``)."""
from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from pyvelm.stub_generators import (
    dependency_closure,
    discover_include_paths,
    ensure_pyrightconfig,
    generate_stubs,
    index_for_modules,
    load_stub_index,
    maybe_refresh_dev_stubs,
    stubs_on_serve_enabled,
    write_pyrightconfig,
)
from pyvelm.tests._isolation import purge_import_prefix


class StubGeneratorTests(unittest.TestCase):
    _MODULE_PREFIXES = ("demo", "base_mod", "partners", "crm")

    def setUp(self):
        for prefix in self._MODULE_PREFIXES:
            purge_import_prefix(prefix)

    def tearDown(self):
        for prefix in self._MODULE_PREFIXES:
            purge_import_prefix(prefix)

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
            self.assertTrue((written / "pyvelm" / "model.pyi").is_file())
            self.assertTrue((written / "pyvelm" / "field_builders.pyi").is_file())
            names = (written / "names.pyi").read_text(encoding="utf-8")
            self.assertIn('"demo.item"', names)
            self.assertIn('"demo.item.list"', names)
            env_stub = (written / "pyvelm" / "env.pyi").read_text(encoding="utf-8")
            self.assertIn("ModelName", env_stub)
            self.assertIn("def query(self, model_name: ModelName) -> Query", env_stub)
            models_stub = (written / "models_stubs.pyi").read_text(encoding="utf-8")
            self.assertIn("def query(self) -> Query", models_stub)
            model_stub = (written / "pyvelm" / "model.pyi").read_text(encoding="utf-8")
            self.assertIn("_inherit: ClassVar[ModelName | str]", model_stub)
            self.assertIn("_name: ClassVar[ModelName | str]", model_stub)
            fields_stub = (written / "pyvelm" / "fields.pyi").read_text(encoding="utf-8")
            self.assertIn("comodel_name: ModelName", fields_stub)
            self.assertIn("def __new__(cls) -> OrmFieldBuilder", fields_stub)
            self.assertIn("OrmFieldBuilder", fields_stub)
            builders_stub = (
                written / "pyvelm" / "field_builders.pyi"
            ).read_text(encoding="utf-8")
            self.assertIn("def comodel(self, name: ModelName)", builders_stub)
            menus_stub = written / "pyvelm" / "builders" / "menus.pyi"
            views_stub = written / "pyvelm" / "builders" / "views.pyi"
            legacy_stub = written / "pyvelm" / "builders" / "legacy.pyi"
            security_stub = written / "pyvelm" / "security.pyi"
            self.assertTrue(menus_stub.is_file())
            self.assertTrue(views_stub.is_file())
            self.assertTrue(legacy_stub.is_file())
            self.assertTrue(security_stub.is_file())
            self.assertIn("ModelName", views_stub.read_text(encoding="utf-8"))
            self.assertIn("ListViewBuilder", views_stub.read_text(encoding="utf-8"))
            self.assertIn("def list_view", legacy_stub.read_text(encoding="utf-8"))
            self.assertIn("grant_model_access", security_stub.read_text(encoding="utf-8"))
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

    def test_render_views_stubs_model_overloads(self):
        from pyvelm.stub_generators import _render_views_stubs

        text = _render_views_stubs()
        self.assertIn("class ListViewBuilder:", text)
        self.assertIn("def model(self, model: ModelName) -> ListViewBuilder", text)
        self.assertIn("class StatWidgetBuilder:", text)

    def test_render_legacy_stubs_model_overloads(self):
        from pyvelm.stub_generators import _render_legacy_stubs

        text = _render_legacy_stubs()
        self.assertIn("model: ModelName", text)
        self.assertIn("def graph_view", text)

    def test_render_security_stubs_model_overloads(self):
        from pyvelm.stub_generators import _render_security_stubs

        text = _render_security_stubs()
        self.assertIn("def grant_model_access", text)
        self.assertIn("model: ModelName", text)

    def test_render_model_stubs_inherit_and_name(self):
        from pyvelm.stub_generators import _render_model_stubs

        text = _render_model_stubs()
        self.assertIn("_inherit: ClassVar[ModelName | str]", text)
        self.assertIn("_name: ClassVar[ModelName | str]", text)

    def test_render_field_builders_stubs_comodel(self):
        from pyvelm.stub_generators import _render_field_builders_stubs

        text = _render_field_builders_stubs()
        self.assertIn("def comodel(self, name: ModelName)", text)

    def test_stubs_on_serve_enabled_default(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PYVELM_STUBS_ON_SERVE", None)
            self.assertTrue(stubs_on_serve_enabled())
        with patch.dict(os.environ, {"PYVELM_STUBS_ON_SERVE": "0"}):
            self.assertFalse(stubs_on_serve_enabled())

    def test_maybe_refresh_dev_stubs_skips_production(self):
        refreshed, msg = maybe_refresh_dev_stubs(runtime_env="production")
        self.assertFalse(refreshed)
        self.assertEqual(msg, "")

    @patch("pyvelm.stub_generators.generate_stubs")
    def test_maybe_refresh_dev_stubs_runs_in_development(self, generate):
        from pyvelm.stub_generators import StubIndex

        generate.return_value = (Path("/tmp/out"), StubIndex(models=["demo.item"]))
        with patch.dict(os.environ, {"PYVELM_STUBS_ON_SERVE": "1"}):
            with patch(
                "pyvelm.stub_generators.write_pyrightconfig", return_value=False,
            ):
                with patch(
                    "pyvelm.scaffolder.find_project_root", return_value=None,
                ):
                    refreshed, msg = maybe_refresh_dev_stubs(runtime_env="development")
        self.assertTrue(refreshed)
        self.assertIn("IDE stubs refreshed", msg)
        generate.assert_called_once()

    def _dependency_chain_project(self, tmp: Path) -> Path:
        root = tmp / "erp"
        root.mkdir()
        (root / "pyvelm.toml").write_text(
            'modules_root = "app/modules"\n', encoding="utf-8"
        )
        modules = root / "app" / "modules"

        def write_module(
            name: str,
            *,
            depends: list[str],
            model_name: str,
            view_name: str,
        ) -> None:
            mod = modules / name
            mod.mkdir(parents=True)
            (mod / "__init__.py").write_text("", encoding="utf-8")
            (mod / "models").mkdir(parents=True)
            (mod / "views").mkdir(parents=True)
            depends_repr = repr(depends)
            (mod / "__pyvelm__.py").write_text(
                textwrap.dedent(
                    f"""
                    NAME = "{name}"
                    VERSION = (0, 1, 0)
                    DEPENDS: list[str] = {depends_repr}
                    DATA: list[str] = ["views/item.py"]
                    """
                ),
                encoding="utf-8",
            )
            (mod / "models" / "__init__.py").write_text(
                f"from . import item  # noqa: F401\n", encoding="utf-8"
            )
            (mod / "models" / "item.py").write_text(
                textwrap.dedent(
                    f"""
                    from pyvelm import BaseModel, Char

                    class Item(BaseModel):
                        _name = "{model_name}"
                        name = Char()
                    """
                ),
                encoding="utf-8",
            )
            (mod / "views" / "item.py").write_text(
                textwrap.dedent(
                    f"""
                    from pyvelm.builders import list_view

                    VIEWS = [
                        list_view("{view_name}", "{model_name}", fields=["name"]),
                    ]
                    """
                ),
                encoding="utf-8",
            )

        write_module(
            "base_mod",
            depends=[],
            model_name="base_mod.country",
            view_name="country.list",
        )
        write_module(
            "partners",
            depends=["base_mod"],
            model_name="partners.partner",
            view_name="partner.list",
        )
        write_module(
            "crm",
            depends=["partners"],
            model_name="crm.lead",
            view_name="lead.list",
        )
        return root

    def test_dependency_closure_includes_transitive_deps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dependency_chain_project(Path(tmp))
            modules_root = root / "app" / "modules"
            _reg, specs, _index = load_stub_index(modules_root=modules_root)
            partners_closure = dependency_closure("partners", specs)
            self.assertEqual(partners_closure, frozenset({"partners", "base_mod"}))
            crm_closure = dependency_closure("crm", specs)
            self.assertEqual(
                crm_closure,
                frozenset({"crm", "partners", "base_mod"}),
            )

    def test_index_for_modules_filters_models_and_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dependency_chain_project(Path(tmp))
            modules_root = root / "app" / "modules"
            _reg, specs, index = load_stub_index(modules_root=modules_root)
            partners_index = index_for_modules(
                dependency_closure("partners", specs),
                index,
            )
            self.assertIn("partners.partner", partners_index.models)
            self.assertIn("base_mod.country", partners_index.models)
            self.assertNotIn("crm.lead", partners_index.models)
            self.assertIn("partners.partner.list", partners_index.qualified_views)
            self.assertIn("base_mod.country.list", partners_index.qualified_views)
            self.assertNotIn("crm.lead.list", partners_index.qualified_views)

    def test_generate_stubs_writes_dependency_scoped_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dependency_chain_project(Path(tmp))
            modules_root = root / "app" / "modules"
            out = root / ".pyvelm" / "typing"
            generate_stubs(out, modules_root=modules_root, include_bundled=False)
            partners_names = (
                out / "scopes" / "partners" / "names.pyi"
            ).read_text(encoding="utf-8")
            crm_names = (out / "scopes" / "crm" / "names.pyi").read_text(
                encoding="utf-8"
            )
            self.assertIn('"partners.partner"', partners_names)
            self.assertIn('"base_mod.country"', partners_names)
            self.assertNotIn('"crm.lead"', partners_names)
            self.assertIn('"crm.lead"', crm_names)
            global_names = (out / "names.pyi").read_text(encoding="utf-8")
            self.assertIn('"crm.lead"', global_names)

    def test_write_pyrightconfig_adds_execution_environments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._dependency_chain_project(Path(tmp))
            modules_root = root / "app" / "modules"
            out = root / ".pyvelm" / "typing"
            _written, index = generate_stubs(
                out, modules_root=modules_root, include_bundled=False
            )
            self.assertTrue(
                write_pyrightconfig(
                    root,
                    stubs_dir=out,
                    module_roots=index.module_roots,
                )
            )
            cfg = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
            envs = cfg["executionEnvironments"]
            partners_env = next(
                env for env in envs if env["root"] == "app/modules/partners"
            )
            self.assertEqual(
                partners_env["stubPath"],
                ".pyvelm/typing/scopes/partners",
            )
            self.assertIn(".pyvelm/typing/scopes/partners", partners_env["extraPaths"])


if __name__ == "__main__":
    unittest.main()
