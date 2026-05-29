"""Additional coverage for ``pyvelm.modules.console.commands`` scaffolders."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm import BUILTIN_MODULE_ROOTS
from pyvelm.console import CommandContext


def _commands_path() -> None:
    root = str(BUILTIN_MODULE_ROOTS[0])
    if root not in sys.path:
        sys.path.insert(0, root)


def _ctx() -> CommandContext:
    ctx = CommandContext()
    ctx.error = MagicMock()
    ctx.info = MagicMock()
    ctx.line = MagicMock()
    ctx.warn = MagicMock()
    return ctx


class MakeCommandCommandMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_command import (  # noqa: E402
            MakeCommandCommand,
        )
        cls.Command = MakeCommandCommand

    def test_missing_namespace_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        self.assertEqual(cmd.handle("badname"), 1)
        cmd._ctx.error.assert_called_once()

    def test_no_pyvelm_toml_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch("console.commands.make_command.find_modules_root", return_value=None):
            self.assertEqual(cmd.handle("demo:run"), 1)

    def test_infer_module_from_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            modules_root = Path(tmp) / "modules"
            mod = modules_root / "inventory"
            mod.mkdir(parents=True)
            (mod / "__pyvelm__.py").write_text("NAME='inventory'\n", encoding="utf-8")
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_command.find_modules_root",
                return_value=modules_root,
            ), patch("console.commands.make_command.Path.cwd", return_value=mod):
                code = cmd.handle("inventory:import")
            self.assertEqual(code, 0)
            self.assertTrue((mod / "commands" / "inventory_import.py").is_file())

    def test_cwd_outside_modules_root_requires_module_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            modules_root = Path(tmp) / "modules"
            modules_root.mkdir()
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_command.find_modules_root",
                return_value=modules_root,
            ), patch(
                "console.commands.make_command.Path.cwd",
                return_value=Path("/elsewhere"),
            ):
                self.assertEqual(cmd.handle("demo:run"), 1)

    def test_invalid_module_name_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch(
            "console.commands.make_command.find_modules_root",
            return_value=Path("/modules"),
        ):
            self.assertEqual(cmd.handle("demo:run", module="9bad"), 1)

    def test_module_not_found_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_command.find_modules_root", return_value=root
            ):
                self.assertEqual(cmd.handle("demo:run", module="missing"), 1)

    def test_existing_file_without_force_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "modules"
            mod = root / "demo"
            cmd_dir = mod / "commands"
            cmd_dir.mkdir(parents=True)
            (mod / "__pyvelm__.py").write_text("NAME='demo'\n", encoding="utf-8")
            (cmd_dir / "demo_run.py").write_text("# old\n", encoding="utf-8")
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_command.find_modules_root", return_value=root
            ):
                self.assertEqual(cmd.handle("demo:run", module="demo"), 1)

    def test_force_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "modules"
            mod = root / "demo"
            cmd_dir = mod / "commands"
            cmd_dir.mkdir(parents=True)
            (mod / "__pyvelm__.py").write_text("NAME='demo'\n", encoding="utf-8")
            target = cmd_dir / "demo_run.py"
            target.write_text("# old\n", encoding="utf-8")
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_command.find_modules_root", return_value=root
            ):
                self.assertEqual(cmd.handle("demo:run", module="demo", force=True), 0)
            self.assertIn("Not implemented yet", target.read_text(encoding="utf-8"))


class MakeMenuCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_menu import MakeMenuCommand  # noqa: E402

        cls.Command = MakeMenuCommand

    def test_missing_view_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        self.assertEqual(cmd.handle(view=None), 1)

    def test_resolve_error_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch(
            "console.commands.make_menu.resolve_module",
            side_effect=ValueError("bad module"),
        ):
            self.assertEqual(cmd.handle(view="item.list"), 1)

    def test_success_updates_menu(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch(
            "console.commands.make_menu.resolve_module",
            return_value=("demo", Path("/root"), Path("/root/demo")),
        ), patch(
            "console.commands.make_menu.generate_menu",
            return_value=Path("/root/demo/views/menu.py"),
        ):
            self.assertEqual(cmd.handle(view="item.list", module="demo"), 0)
        cmd._ctx.info.assert_called_once()


class MakeModelCommandMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_model import MakeModelCommand  # noqa: E402

        cls.Command = MakeModelCommand

    def test_success_with_vellum(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch(
            "console.commands.make_model.resolve_module",
            return_value=("demo", Path("/root"), Path("/root/demo")),
        ), patch(
            "console.commands.make_model.generate_model",
            return_value=Path("/root/demo/models/item.py"),
        ):
            code = cmd.handle("item", module="demo", vellum=True, force=True)
        self.assertEqual(code, 0)
        self.assertEqual(cmd._ctx.line.call_count, 2)

    def test_file_exists_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch(
            "console.commands.make_model.resolve_module",
            return_value=("demo", Path("/root"), Path("/root/demo")),
        ), patch(
            "console.commands.make_model.generate_model",
            side_effect=FileExistsError("exists"),
        ):
            self.assertEqual(cmd.handle("item"), 1)


class MakeModuleCommandMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_module import MakeModuleCommand  # noqa: E402

        cls.Command = MakeModuleCommand

    def test_missing_pyvelm_toml_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch("console.commands.make_module.find_modules_root", return_value=None):
            self.assertEqual(cmd.handle("tasks"), 1)

    def test_find_modules_root_when_arg_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch(
                "console.commands.make_module.find_modules_root", return_value=root
            ), patch("console.commands.make_module.materialise"), patch(
                "console.commands.make_module.echo_next_steps_for_new"
            ):
                self.assertEqual(cmd.handle("tasks"), 0)

    def test_file_exists_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks").mkdir()
            cmd = self.Command()
            cmd._ctx = _ctx()
            with patch("console.commands.make_module.materialise", side_effect=FileExistsError):
                self.assertEqual(cmd.handle("tasks", modules_root=str(root)), 1)


class MakeStubsCommandMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_stubs import MakeStubsCommand  # noqa: E402

        cls.Command = MakeStubsCommand

    def test_default_output_from_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "pyvelm.toml").write_text("modules_root='m'\n", encoding="utf-8")
            out = project / ".pyvelm" / "typing"
            cmd = self.Command()
            cmd._ctx = _ctx()
            index = MagicMock()
            index.models = {"a": 1}
            index.qualified_views = {"b": 1}
            with patch("console.commands.make_stubs._load_dotenv_for_scaffold"), patch(
                "console.commands.make_stubs.find_project_root", return_value=project
            ), patch(
                "console.commands.make_stubs.generate_stubs",
                return_value=(out, index),
            ), patch("console.commands.make_stubs.write_pyrightconfig", return_value=True):
                self.assertEqual(cmd.handle(), 0)
            cmd._ctx.warn.assert_not_called()

    def test_warns_when_no_project_and_no_output(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        index = MagicMock()
        index.models = {}
        index.qualified_views = {}
        with patch("console.commands.make_stubs._load_dotenv_for_scaffold"), patch(
            "console.commands.make_stubs.find_project_root", return_value=None
        ), patch(
            "console.commands.make_stubs.generate_stubs",
            return_value=(Path("/tmp/out"), index),
        ), patch("console.commands.make_stubs.write_pyrightconfig", return_value=False):
            self.assertEqual(cmd.handle(), 0)
        cmd._ctx.warn.assert_called_once()

    def test_generate_failure_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch("console.commands.make_stubs._load_dotenv_for_scaffold"), patch(
            "console.commands.make_stubs.find_project_root", return_value=None
        ), patch(
            "console.commands.make_stubs.generate_stubs",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(cmd.handle(output="/tmp/out"), 1)


class MakeViewCommandMoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_view import MakeViewCommand  # noqa: E402

        cls.Command = MakeViewCommand

    def test_success_from_model_fields(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        registry = MagicMock()
        with patch("console.commands.make_view._load_dotenv_for_scaffold"), patch(
            "console.commands.make_view.resolve_module",
            return_value=("demo", Path("/root"), Path("/root/demo")),
        ), patch(
            "console.commands.make_view.load_registry_for_module",
            return_value=registry,
        ), patch(
            "console.commands.make_view.generate_views",
            return_value=Path("/root/demo/views/item.py"),
        ), patch(
            "pyvelm.scaffold_generators.normalize_model_for_views",
            return_value=("demo.item", "item", None),
        ):
            code = cmd.handle("demo.item", module="demo")
        self.assertEqual(code, 0)
        cmd._ctx.line.assert_called_once()

    def test_minimal_stub_skips_registry(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch("console.commands.make_view._load_dotenv_for_scaffold"), patch(
            "console.commands.make_view.resolve_module",
            return_value=("demo", Path("/root"), Path("/root/demo")),
        ), patch("console.commands.make_view.load_registry_for_module") as load_reg, patch(
            "console.commands.make_view.generate_views",
            return_value=Path("/root/demo/views/item.py"),
        ), patch(
            "pyvelm.scaffold_generators.normalize_model_for_views",
            return_value=("demo.item", "item", None),
        ):
            code = cmd.handle("demo.item", minimal=True)
        self.assertEqual(code, 0)
        load_reg.assert_not_called()

    def test_file_exists_returns_error(self):
        cmd = self.Command()
        cmd._ctx = _ctx()
        with patch("console.commands.make_view._load_dotenv_for_scaffold"), patch(
            "console.commands.make_view.resolve_module",
            side_effect=FileExistsError("exists"),
        ):
            self.assertEqual(cmd.handle("demo.item"), 1)


if __name__ == "__main__":
    unittest.main()
