"""Unit tests for ``pyvelm.scaffold_generators``."""
from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Boolean, Char, Integer, Many2many, Many2one, One2many
from pyvelm.registry import Registry
from pyvelm.scaffold_generators import (
    _field_view_ref,
    _format_field_list,
    _format_form_sections,
    _minimal_view_fields,
    _ordered_stored_fields,
    _read_template,
    _title_from_model,
    append_manifest_data,
    append_models_init,
    build_view_scaffold_from_model,
    class_name_from_stem,
    ensure_views_for_models,
    generate_menu,
    generate_model,
    generate_views,
    infer_module_for_model,
    list_view_files,
    load_registry_for_module,
    model_has_list_view,
    model_stem,
    models_affected_by_diff,
    modules_root_candidates,
    normalize_model_for_views,
    resolve_module,
)
from pyvelm.tests._isolation import purge_import_prefix


def _demo_module(root: Path, name: str = "demo") -> Path:
    mod = root / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "__init__.py").write_text("", encoding="utf-8")
    (mod / "models").mkdir(parents=True)
    (mod / "views").mkdir(exist_ok=True)
    (mod / "__pyvelm__.py").write_text(
        textwrap.dedent(
            f"""
            NAME = "{name}"
            VERSION = (0, 1, 0)
            DEPENDS: list[str] = []
            DATA: list[str] = []
            """
        ),
        encoding="utf-8",
    )
    (mod / "models" / "__init__.py").write_text(
        '"""Models."""\n', encoding="utf-8"
    )
    return mod


class HelperTests(unittest.TestCase):
    def test_class_name_from_stem(self):
        self.assertEqual(class_name_from_stem("sale_order"), "SaleOrder")
        self.assertEqual(class_name_from_stem("a.b"), "AB")

    def test_title_from_model(self):
        self.assertEqual(_title_from_model("demo.sale_order"), "Sale Order")

    def test_read_template_substitutes(self):
        body = _read_template(
            "snippets/model.py.template",
            {"module": "demo", "model": "demo.item", "class_name": "Item"},
        )
        self.assertIn("class Item", body)
        self.assertIn('"demo.item"', body)

    def test_read_template_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            _read_template("missing/template.txt", {})

    def test_format_helpers(self):
        lines = _format_field_list(['"name"', 'field("active", widget="toggle")'])
        self.assertIn('"name"', lines)
        sections = _format_form_sections([("main", "Main", ['"name"'])])
        self.assertIn('section("main"', sections)


class NormalizeModelTests(unittest.TestCase):
    def test_short_name_gets_module_prefix(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "demo.item"
                name = Char()

        file_stem, view_stem, technical = normalize_model_for_views(
            "item", "demo", reg
        )
        self.assertEqual(technical, "demo.item")
        self.assertEqual(file_stem, "item")
        self.assertEqual(view_stem, "item")

    def test_invalid_stem_raises(self):
        with self.assertRaises(ValueError):
            normalize_model_for_views("bad-name", "demo", None)

    def test_unknown_model_raises_with_registry(self):
        reg = Registry()
        with reg.activate():
            pass
        with self.assertRaises(ValueError):
            normalize_model_for_views("demo.missing", "demo", reg)

    def test_full_technical_name_in_registry(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "other.item"
                name = Char()

        file_stem, view_stem, technical = normalize_model_for_views(
            "other.item", "demo", reg
        )
        self.assertEqual(technical, "other.item")
        self.assertEqual(view_stem, "item")

    def test_model_stem_legacy(self):
        self.assertEqual(model_stem("demo.partner", "demo"), "partner")


class ManifestAndInitTests(unittest.TestCase):
    def test_append_manifest_and_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            manifest = mod / "__pyvelm__.py"
            self.assertTrue(
                append_manifest_data(manifest, "views/partner.py")
            )
            self.assertFalse(
                append_manifest_data(manifest, "views/partner.py")
            )
            init = mod / "models" / "__init__.py"
            self.assertTrue(append_models_init(init, "partner"))
            self.assertFalse(append_models_init(init, "partner"))

    def test_append_manifest_no_data_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            (mod / "__pyvelm__.py").write_text("NAME='x'\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                append_manifest_data(mod / "__pyvelm__.py", "views/x.py")

    def test_append_manifest_with_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            manifest = mod / "__pyvelm__.py"
            manifest.write_text(
                'NAME = "demo"\nVERSION = (0, 1, 0)\nDATA: list[str] = ["views/a.py",]\n',
                encoding="utf-8",
            )
            self.assertTrue(append_manifest_data(manifest, "views/b.py"))

    def test_append_manifest_empty_data_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            manifest = mod / "__pyvelm__.py"
            manifest.write_text(
                'NAME = "demo"\nVERSION = (0, 1, 0)\nDATA: list[str] = []\n',
                encoding="utf-8",
            )
            self.assertTrue(append_manifest_data(manifest, "views/x.py"))

    def test_append_models_init_without_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            init = Path(tmp) / "__init__.py"
            init.write_text("x = 1", encoding="utf-8")
            self.assertTrue(append_models_init(init, "foo"))
            self.assertTrue(init.read_text(encoding="utf-8").endswith("\n"))

    def test_append_models_init_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            init = Path(tmp) / "__init__.py"
            init.write_text("", encoding="utf-8")
            self.assertTrue(append_models_init(init, "foo"))
            self.assertIn("import foo", init.read_text(encoding="utf-8"))


class ModulesRootTests(unittest.TestCase):
    def test_explicit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(modules_root_candidates(root), [root.resolve()])

    @patch("pyvelm.scaffold_generators._load_dotenv_for_scaffold")
    @patch("pyvelm.scaffold_generators.find_modules_root", return_value=None)
    @patch("pyvelm.cli._default_module_roots")
    def test_candidates_from_cli_roots(self, default_roots, _marker, _dotenv):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_roots.return_value = [root]
            out = modules_root_candidates()
            self.assertEqual(out, [root.resolve()])

    @patch("pyvelm.scaffold_generators._load_dotenv_for_scaffold")
    @patch("pyvelm.scaffold_generators.find_modules_root")
    @patch("pyvelm.cli._default_module_roots")
    def test_candidates_deduplicate_roots(
        self, default_roots, marker_root, _dotenv
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker_root.return_value = root
            default_roots.return_value = [root]
            out = modules_root_candidates()
            self.assertEqual(len(out), 1)

    @patch("pyvelm.scaffold_generators._load_dotenv_for_scaffold")
    @patch("pyvelm.scaffold_generators.find_modules_root", return_value=None)
    @patch("pyvelm.cli._default_module_roots")
    def test_candidates_skip_non_directory_roots(self, default_roots, _marker, _dotenv):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "notadir"
            file_path.write_text("x", encoding="utf-8")
            default_roots.return_value = [file_path, root]
            out = modules_root_candidates()
            self.assertEqual(out, [root.resolve()])

    @patch("pyvelm.scaffold_generators._load_dotenv_for_scaffold")
    def test_load_dotenv_import_error_swallowed(self, _fn):
        with patch.dict(sys.modules, {"dotenv": None}):
            import pyvelm.scaffold_generators as sg

            importlib.reload(sg)
            sg._load_dotenv_for_scaffold()  # should not raise


class ResolveModuleTests(unittest.TestCase):
    def test_resolve_from_cwd_outside_roots_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _demo_module(root, "myaddon")
            import os

            cwd = Path.cwd()
            try:
                os.chdir("/tmp")
                with patch(
                    "pyvelm.scaffold_generators.modules_root_candidates",
                    return_value=[root],
                ):
                    with self.assertRaises(ValueError):
                        resolve_module(None, modules_root=root)
            finally:
                os.chdir(cwd)

    def test_resolve_from_cwd_inside_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = _demo_module(root, "myaddon")
            cwd = Path.cwd()
            try:
                import os

                os.chdir(mod)
                name, mod_root, mod_path = resolve_module(
                    None, modules_root=root
                )
                self.assertEqual(name, "myaddon")
                self.assertEqual(mod_path, mod.resolve())
            finally:
                os.chdir(cwd)

    def test_resolve_by_model_name(self):
        purge_import_prefix("demo")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = _demo_module(root)
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
            (mod / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            sys.path.insert(0, str(root))
            try:
                name, _, path = resolve_module(
                    None, model_name="demo.item", modules_root=root
                )
                self.assertEqual(name, "demo")
                self.assertTrue((path / "__pyvelm__.py").is_file())
            finally:
                sys.path.remove(str(root))
                purge_import_prefix("demo")

    def test_resolve_invalid_module_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _demo_module(root)
            with patch(
                "pyvelm.scaffold_generators.modules_root_candidates",
                return_value=[root],
            ):
                with self.assertRaises(ValueError):
                    resolve_module("bad-name!", modules_root=root)

    def test_resolve_errors(self):
        with patch(
            "pyvelm.scaffold_generators.modules_root_candidates",
            return_value=[],
        ):
            with self.assertRaises(ValueError):
                resolve_module("demo")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(
                "pyvelm.scaffold_generators.modules_root_candidates",
                return_value=[root],
            ):
                with self.assertRaises(ValueError):
                    resolve_module("missing_mod", modules_root=root)

    def test_infer_module_suffix_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = _demo_module(root)
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
            (mod / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            sys.path.insert(0, str(root))
            try:
                self.assertEqual(
                    infer_module_for_model("item", [root]), "demo"
                )
            finally:
                sys.path.remove(str(root))
                purge_import_prefix("demo")

    def test_infer_module_direct_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _demo_module(root)
            (root / "demo" / "models" / "item.py").write_text(
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
            (root / "demo" / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            purge_import_prefix("demo")
            sys.path.insert(0, str(root))
            try:
                self.assertEqual(
                    infer_module_for_model("demo.item", [root]), "demo"
                )
            finally:
                sys.path.remove(str(root))
                purge_import_prefix("demo")

    def test_infer_module_unknown_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _demo_module(root)
            with self.assertRaises(ValueError):
                infer_module_for_model("unknown.model", [root])


class FieldViewRefTests(unittest.TestCase):
    def test_widget_refs(self):
        self.assertIn("toggle", _field_view_ref("active", Boolean()))
        self.assertIn("dialog", _field_view_ref("lines", One2many("x", "y")))
        self.assertIn("dialog", _field_view_ref("tags", Many2many("x")))
        self.assertEqual(_field_view_ref("name", Char()), '"name"')


class BuildViewScaffoldEdgeTests(unittest.TestCase):
    def test_build_raises_for_unknown_model(self):
        reg = Registry()
        with reg.activate():
            pass
        with self.assertRaises(ValueError):
            build_view_scaffold_from_model(reg, "demo.missing")

    def test_max_list_fields_and_empty_sections_fallback(self):
        reg = Registry()
        with reg.activate():

            class Wide(BaseModel):
                _name = "demo.wide"
                f1 = Char()
                f2 = Char()
                f3 = Char()
                f4 = Char()
                f5 = Char()
                f6 = Char()
                f7 = Char()
                f8 = Char()
                f9 = Char()
                f10 = Char()
                f11 = Char()
                f12 = Char()
                f13 = Char()

        lines, sections = build_view_scaffold_from_model(
            reg, "demo.wide", max_list_fields=3
        )
        self.assertEqual(len(lines), 3)

    def test_non_stored_field_skipped(self):
        from pyvelm import depends

        reg = Registry()
        with reg.activate():

            class X(BaseModel):
                _name = "demo.x"
                name = Char()
                total = Integer(compute="_c", store=False)

                @depends("name")
                def _c(self):
                    pass

        ordered = _ordered_stored_fields(reg["demo.x"])
        names = [n for n, _ in ordered]
        self.assertIn("name", names)
        self.assertNotIn("total", names)


class BuildViewScaffoldTests(unittest.TestCase):
    def tearDown(self):
        purge_import_prefix("demo")

    def test_only_non_stored_fields_use_id_fallback_section(self):
        from pyvelm import depends

        reg = Registry()
        with reg.activate():

            class Ghost(BaseModel):
                _name = "demo.ghost"
                _timestamps = False
                note = Char(compute="_c", store=False)

                @depends("id")
                def _c(self):
                    pass

        lines, sections = build_view_scaffold_from_model(reg, "demo.ghost")
        self.assertIn('"id"', lines)
        self.assertEqual(sections[0][0], "main")

    def test_list_adds_timestamp_when_room(self):
        reg = Registry()
        with reg.activate():

            class T(BaseModel):
                _name = "demo.t"
                _timestamps = True
                name = Char()

        lines, _ = build_view_scaffold_from_model(
            reg, "demo.t", max_list_fields=2
        )
        self.assertIn('"created_at"', lines)

    def test_list_truncation_with_relations_and_timestamps(self):
        reg = Registry()
        with reg.activate():

            class Busy(BaseModel):
                _name = "demo.busy"
                _timestamps = True
                a = Char()
                b = Char()
                c = Char()
                d = Char()
                e = Char()
                tag_ids = Many2many("demo.busy")

        lines, _sections = build_view_scaffold_from_model(
            reg, "demo.busy", max_list_fields=4
        )
        self.assertEqual(len(lines), 4)

    def test_model_without_name_uses_id(self):
        reg = Registry()
        with reg.activate():

            class CodeOnly(BaseModel):
                _name = "demo.code_only"
                code = Char()

        lines, sections = build_view_scaffold_from_model(reg, "demo.code_only")
        self.assertIn('"code"', lines)
        self.assertTrue(sections)

    def test_minimal_view_fields(self):
        lines, sections = _minimal_view_fields("demo.item")
        self.assertEqual(lines, ['"name"'])
        self.assertEqual(sections[0][0], "main")

    def test_ordered_stored_fields_respects_timestamps(self):
        reg = Registry()
        with reg.activate():

            class T(BaseModel):
                _name = "demo.ts"
                _timestamps = True
                name = Char()
                note = Char()
                amount = Integer()

        cls = reg["demo.ts"]
        ordered = _ordered_stored_fields(cls)
        names = [n for n, _ in ordered]
        self.assertEqual(names[0], "name")
        self.assertIn("created_at", names)


class GenerateModelTests(unittest.TestCase):
    def tearDown(self):
        purge_import_prefix("demo")

    def test_generate_model_and_vellum(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            path = generate_model(mod, "demo", "partner")
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("demo.partner", text)
            with self.assertRaises(FileExistsError):
                generate_model(mod, "demo", "partner")
            vpath = generate_model(
                mod, "demo", "note", force=True, vellum=True
            )
            self.assertIn("Vellum", vpath.read_text(encoding="utf-8"))


class GenerateViewsTests(unittest.TestCase):
    def tearDown(self):
        purge_import_prefix("demo")

    def test_generate_views_minimal_and_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            path = generate_views(
                mod, "demo", "item", registry=None, from_model=False
            )
            self.assertIn("demo.item", path.read_text(encoding="utf-8"))
            manifest = (mod / "__pyvelm__.py").read_text(encoding="utf-8")
            self.assertIn("views/item.py", manifest)
            path2 = generate_views(
                mod, "demo", "item", force=True, from_model=False
            )
            self.assertEqual(path, path2)

    def test_generate_views_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = _demo_module(root)
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
            (mod / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            sys.path.insert(0, str(root))
            try:
                reg = load_registry_for_module("demo", modules_root=root)
                path = generate_views(
                    mod, "demo", "item", registry=reg, from_model=True
                )
                self.assertIn('"name"', path.read_text(encoding="utf-8"))
            finally:
                sys.path.remove(str(root))

    def test_generate_views_exists_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            generate_views(mod, "demo", "item", from_model=False)
            with self.assertRaises(FileExistsError):
                generate_views(mod, "demo", "item", from_model=False)

    def test_generate_views_unknown_module_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            with self.assertRaises(ValueError):
                generate_views(
                    mod, "nope", "item", from_model=True
                )

    def test_load_registry_missing_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _demo_module(root, "other")
            self.assertIsNone(
                load_registry_for_module("ghost", modules_root=root)
            )

    def test_load_registry_module_not_in_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                load_registry_for_module("demo", modules_root=Path(tmp))
            )

    def test_load_registry_fallthrough_returns_none(self):
        with (
            patch("pyvelm.loader.discover", return_value={"demo": MagicMock()}),
            patch("pyvelm.loader.resolve_order", return_value=[]),
            patch("pyvelm.loader._load_models"),
        ):
            self.assertIsNone(
                load_registry_for_module("demo", modules_root=Path("/tmp"))
            )


class GenerateMenuTests(unittest.TestCase):
    def test_generate_menu_new_and_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            path = generate_menu(
                mod,
                "demo",
                view_name="demo.item.list",
                group_label="Demo App",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("demo.item.list", text)
            manifest = (mod / "__pyvelm__.py").read_text(encoding="utf-8")
            self.assertIn("views/menu.py", manifest)
            generate_menu(
                mod,
                "demo",
                view_name="demo.item.list",
                append=True,
            )
            self.assertIn("demo.item.list", path.read_text(encoding="utf-8"))
            generate_menu(
                mod,
                "demo",
                view_name="demo.other.list",
                item_name="demo.other",
                append=True,
            )

    def test_generate_menu_duplicate_returns_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            path = generate_menu(
                mod,
                "demo",
                view_name="demo.x.list",
                item_name="demo.x",
                item_label="X",
            )
            generate_menu(
                mod,
                "demo",
                view_name="demo.x.list",
                item_name="demo.x",
                item_label="X",
                append=True,
            )
            again = generate_menu(
                mod,
                "demo",
                view_name="demo.x.list",
                item_name="demo.x",
                item_label="X",
                append=True,
            )
            self.assertEqual(path, again)

    def test_generate_menu_exists_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            generate_menu(mod, "demo", view_name="demo.x.list")
            with self.assertRaises(FileExistsError):
                generate_menu(mod, "demo", view_name="demo.y.list")

    def test_generate_menu_bad_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = _demo_module(Path(tmp))
            menu = mod / "views" / "menu.py"
            menu.write_text("not a menu\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                generate_menu(
                    mod, "demo", view_name="demo.x.list", append=True
                )


class ListViewFilesTests(unittest.TestCase):
    def test_list_view_files_empty_and_populated(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp)
            self.assertEqual(list_view_files(mod), [])
            views = mod / "views"
            views.mkdir()
            (views / "a.py").write_text("# x\n", encoding="utf-8")
            files = list_view_files(mod)
            self.assertEqual(len(files), 1)


class TimestampScaffoldTests(unittest.TestCase):
    def test_timestamp_names_import_error(self):
        from pyvelm.scaffold_generators import _timestamp_field_names

        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "demo.ts2"
                name = Char()

        with patch.dict(sys.modules, {"pyvelm.timestamps": None}):
            self.assertEqual(_timestamp_field_names(reg["demo.ts2"]), [])

    def test_timestamp_names_when_enabled(self):
        from pyvelm.scaffold_generators import _timestamp_field_names

        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "demo.ts3"
                _timestamps = True
                name = Char()

        names = _timestamp_field_names(reg["demo.ts3"])
        self.assertTrue(names)

    def test_timestamp_names_disabled(self):
        from pyvelm.scaffold_generators import _timestamp_field_names

        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "demo.ts4"
                _timestamps = False
                name = Char()

        self.assertEqual(_timestamp_field_names(reg["demo.ts4"]), [])


class EnsureViewsAndDiffTests(unittest.TestCase):
    def tearDown(self):
        purge_import_prefix("demo")

    def test_models_affected_by_diff(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "demo.partner"
                name = Char()

        reg._model_module["demo.partner"] = "demo"
        env = MagicMock()
        env.registry = reg
        diff = MagicMock()
        diff.new_tables = [(Partner._table, "CREATE")]
        diff.new_columns = [(Partner._table, "email", "ALTER", False, "text")]
        models = models_affected_by_diff(env, "demo", diff)
        self.assertIn("demo.partner", models)
        other_reg = Registry()
        with other_reg.activate():

            class Other(BaseModel):
                _name = "other.x"
                name = Char()

        other_reg._model_module["other.x"] = "other"
        env.registry = other_reg
        self.assertEqual(models_affected_by_diff(env, "demo", diff), [])

    def test_ensure_views_skips_existing_and_creates(self):
        from pyvelm.loader import ModuleSpec

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = _demo_module(root)
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
            (mod / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            sys.path.insert(0, str(root))
            try:
                spec = ModuleSpec(
                    name="demo",
                    version=(0, 1, 0),
                    depends=[],
                    package="demo",
                    models_package="demo.models",
                    migrations_package="demo.migrations",
                    package_path=mod,
                )
                spec.views = [
                    {
                        "name": "item.list",
                        "model": "demo.item",
                        "view_type": "list",
                    }
                ]
                reg = load_registry_for_module("demo", modules_root=root)
                created = ensure_views_for_models(
                    spec, ["demo.item"], registry=reg
                )
                self.assertEqual(created, [])
                self.assertTrue(model_has_list_view(spec, "demo.item"))
                with patch(
                    "pyvelm.scaffold_generators.model_has_list_view",
                    return_value=False,
                ):
                    created2 = ensure_views_for_models(
                        spec,
                        ["demo.item"],
                        registry=reg,
                        force=True,
                    )
                self.assertEqual(len(created2), 1)
            finally:
                sys.path.remove(str(root))

    def test_ensure_views_no_package_path(self):
        from pyvelm.loader import ModuleSpec

        spec = ModuleSpec(
            name="demo",
            version=(0, 1, 0),
            depends=[],
            package="demo",
            models_package="demo.models",
            migrations_package="demo.migrations",
            package_path=None,
        )
        self.assertEqual(ensure_views_for_models(spec, ["demo.item"]), [])


if __name__ == "__main__":
    unittest.main()
