"""Apps upgrade/sync: reload DATA and apply_schema_diff."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pyvelm.loader import ModuleSpec, _load_data_files


class DataFileReloadTests(unittest.TestCase):
    def test_load_data_files_reload_picks_up_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "views").mkdir()
            view_py = root / "views" / "demo.py"
            view_py.write_text('VIEWS = [{"name": "a.list"}]\n', encoding="utf-8")
            spec = ModuleSpec(
                name="tmpmod",
                version=(0, 1, 0),
                depends=[],
                package="tmpmod",
                models_package="tmpmod.models",
                migrations_package=None,
                package_path=root,
                data=["views/demo.py"],
            )
            _load_data_files(spec)
            self.assertEqual(len(spec.views), 1)
            self.assertEqual(spec.views[0]["name"], "a.list")

            view_py.write_text(
                'VIEWS = [{"name": "a.list"}, {"name": "b.list"}]\n',
                encoding="utf-8",
            )
            _load_data_files(spec)
            self.assertEqual(len(spec.views), 2)


class ApplySchemaDiffTests(unittest.TestCase):
    def test_empty_diff_is_noop(self):
        from pyvelm.db_autogen import ApplyResult

        r = ApplyResult()
        self.assertTrue(r.is_empty)
        self.assertEqual(r.summary(), "schema unchanged")

    def test_result_not_empty_when_not_null_applied(self):
        from pyvelm.db_autogen import ApplyResult

        r = ApplyResult(set_not_null=1)
        self.assertFalse(r.is_empty)
        self.assertIn("NOT NULL", r.summary())


class ReloadModelsRegistryTests(unittest.TestCase):
    def test_reload_models_activates_registry(self):
        import sys
        import textwrap

        from pyvelm.loader import ModuleSpec, _load_models, reload_models
        from pyvelm.registry import Registry

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "tmpmod"
            (pkg / "models").mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "models" / "__init__.py").write_text(
                "from .thing import Thing\n", encoding="utf-8"
            )
            (pkg / "models" / "thing.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.model import BaseModel
                    from pyvelm.fields import Char

                    class Thing(BaseModel):
                        _name = "tmp.thing"
                        label = Char()
                    """
                ),
                encoding="utf-8",
            )
            root_str = str(root)
            if root_str not in sys.path:
                sys.path.insert(0, root_str)
            try:
                spec = ModuleSpec(
                    name="tmpmod",
                    version=(0, 1, 0),
                    depends=[],
                    package="tmpmod",
                    models_package="tmpmod.models",
                    migrations_package=None,
                    package_path=pkg,
                )
                reg = Registry()
                _load_models(spec, reg)
                self.assertIn("tmp.thing", reg._models)
                reload_models(spec, reg)
                self.assertIn("tmp.thing", reg._models)
            finally:
                if root_str in sys.path:
                    sys.path.remove(root_str)
                for key in list(sys.modules):
                    if key == "tmpmod.models" or key.startswith("tmpmod.models."):
                        del sys.modules[key]


if __name__ == "__main__":
    unittest.main()
