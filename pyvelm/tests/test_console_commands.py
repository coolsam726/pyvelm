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


class ServeCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.serve import ServeCommand  # noqa: E402

        cls.Command = ServeCommand

    def _ctx(self, roots=None):
        ctx = CommandContext(roots=roots or [])
        ctx.error = MagicMock()
        return ctx

    def test_invalid_port(self):
        cmd = self.Command()
        cmd._ctx = self._ctx()
        code = cmd.handle(port="not-a-port")
        self.assertEqual(code, 1)
        cmd._ctx.error.assert_called_once()

    def test_reload_without_app_guesses_or_errors(self):
        cmd = self.Command()
        cmd._ctx = self._ctx()
        with patch(
            "console.commands.serve.guess_serve_import", return_value=None,
        ):
            code = cmd.handle(reload=True)
        self.assertEqual(code, 1)

    @patch("console.commands.serve.run_dev_server")
    @patch("console.commands.serve.build_serve_app")
    def test_serve_without_reload(self, build_app, run_server):
        app = MagicMock()
        build_app.return_value = app
        cmd = self.Command()
        cmd._ctx = self._ctx(roots=[MagicMock()])
        code = cmd.handle(host="0.0.0.0", port="9000", env="production")
        self.assertEqual(code, 0)
        build_app.assert_called_once()
        run_server.assert_called_once()
        self.assertIs(run_server.call_args.kwargs["app"], app)
        self.assertEqual(run_server.call_args.kwargs["port"], 9000)


class MigrateCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.migrate import (  # noqa: E402
            MigrateCommand,
            MigrateFreshCommand,
            MigrateResetCommand,
        )

        cls.Migrate = MigrateCommand
        cls.MigrateFresh = MigrateFreshCommand
        cls.MigrateReset = MigrateResetCommand

    def _ctx(self):
        return CommandContext(roots=[])

    @patch("console.commands.migrate.run_migrate")
    def test_migrate_delegates(self, run_migrate):
        cmd = self.Migrate()
        cmd._ctx = self._ctx()
        code = cmd.handle(all=True, module="partners")
        self.assertEqual(code, 0)
        run_migrate.assert_called_once_with(
            [],
            install_all=True,
            only_module="partners",
        )

    @patch("console.commands.migrate.run_migrate_fresh")
    def test_migrate_fresh_delegates(self, run_fresh):
        cmd = self.MigrateFresh()
        cmd._ctx = self._ctx()
        code = cmd.handle(yes=True, schema="public", all=False, module=None)
        self.assertEqual(code, 0)
        run_fresh.assert_called_once()

    @patch("console.commands.migrate.run_migrate_reset")
    def test_migrate_reset_delegates(self, run_reset):
        cmd = self.MigrateReset()
        cmd._ctx = self._ctx()
        code = cmd.handle(yes=True, schema="custom")
        self.assertEqual(code, 0)
        run_reset.assert_called_once_with([], schema="custom", yes=True)


class TestCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _commands_path()
        from console.commands.test import TestCommand, default_test_path  # noqa: E402

        cls.Command = TestCommand

    def test_default_test_path_in_pyvelm_repo(self):
        from console.commands.test import default_test_path

        if Path("pyvelm/tests").is_dir():
            self.assertEqual(default_test_path(), "pyvelm/tests")

    def test_missing_pytest_returns_error(self):
        cmd = self.Command()
        ctx = CommandContext()
        ctx.error = MagicMock()
        cmd._ctx = ctx
        real_import = __import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pytest":
                raise ImportError("no pytest")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guarded_import):
            code = cmd.run(ctx, [])
        self.assertEqual(code, 1)
        ctx.error.assert_called_once()

    def test_run_invokes_pytest_main(self):
        cmd = self.Command()
        ctx = CommandContext()
        cmd._ctx = ctx
        with patch("pytest.main", return_value=0) as main:
            code = cmd.run(ctx, ["--path", "pyvelm/tests", "-k", "foo"])
        self.assertEqual(code, 0)
        main.assert_called_once()
        args = main.call_args[0][0]
        self.assertIn("pyvelm/tests", args)
        self.assertIn("-k", args)
        self.assertIn("foo", args)
        self.assertIn("-m", args)
        self.assertEqual(args[args.index("-m") + 1], "not integration")


if __name__ == "__main__":
    unittest.main()
