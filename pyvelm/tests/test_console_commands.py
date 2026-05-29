"""Tests for bundled ``pyvelm.modules.console.commands`` scaffolders."""
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


class MakeModuleCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_module import MakeModuleCommand  # noqa: E402

        cls.Command = MakeModuleCommand

    def _ctx(self):
        ctx = CommandContext()
        ctx.error = MagicMock()
        ctx.info = MagicMock()
        ctx.line = MagicMock()
        return ctx

    def test_invalid_name_returns_error(self):
        cmd = self.Command()
        cmd._ctx = self._ctx()
        code = cmd.handle("9bad", None)
        self.assertEqual(code, 1)
        cmd._ctx.error.assert_called_once()

    def test_success_scaffolds_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "modules"
            root.mkdir()
            cmd = self.Command()
            cmd._ctx = self._ctx()
            with patch("console.commands.make_module.materialise") as mat, patch(
                "console.commands.make_module.echo_next_steps_for_new"
            ):
                code = cmd.handle("tasks", str(root))
            self.assertEqual(code, 0)
            mat.assert_called_once()


class MakeViewCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_view import MakeViewCommand  # noqa: E402

        cls.Command = MakeViewCommand

    def test_resolve_error_returns_1(self):
        cmd = self.Command()
        ctx = CommandContext()
        ctx.error = MagicMock()
        cmd._ctx = ctx
        with patch(
            "console.commands.make_view.resolve_module",
            side_effect=ValueError("bad"),
        ), patch("console.commands.make_view._load_dotenv_for_scaffold"):
            code = cmd.handle("demo.item", module=None)
        self.assertEqual(code, 1)


class MakeModelCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_model import MakeModelCommand  # noqa: E402

        cls.Command = MakeModelCommand

    def test_value_error_returns_error_code(self):
        cmd = self.Command()
        ctx = CommandContext()
        ctx.error = MagicMock()
        cmd._ctx = ctx
        with patch(
            "console.commands.make_model.resolve_module",
            side_effect=ValueError("unknown module"),
        ):
            code = cmd.handle("task", module=None)
        self.assertEqual(code, 1)
        ctx.error.assert_called_once()


class MakeStubsCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.make_stubs import MakeStubsCommand  # noqa: E402

        cls.Command = MakeStubsCommand

    def test_writes_stubs_to_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "typing"
            cmd = self.Command()
            ctx = CommandContext()
            ctx.info = MagicMock()
            ctx.line = MagicMock()
            cmd._ctx = ctx
            index = MagicMock()
            index.models = {}
            index.views = {}
            with patch("console.commands.make_stubs.generate_stubs", return_value=(["a.pyi"], index)), patch(
                "console.commands.make_stubs.write_pyrightconfig"
            ), patch("console.commands.make_stubs._load_dotenv_for_scaffold"), patch(
                "console.commands.make_stubs.find_project_root", return_value=None
            ):
                code = cmd.run(ctx, [f"--output={out}"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
