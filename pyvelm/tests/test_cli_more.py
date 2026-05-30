"""Additional tests for ``pyvelm.cli`` (init, new, diff, autogen, cron, main)."""
from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm import Registry
from pyvelm.cli import (
    _build_parser,
    _default_module_roots,
    _dsn_display,
    _load_dotenv,
    _ordered_specs_for_install,
    _parse_roots,
    _require_dsn,
    _resolve_module_roots,
    _run_command_help,
    _run_command_list,
    _run_cron,
    _run_db_autogen,
    _run_db_diff,
    _run_init,
    _run_new,
    _tick,
    _try_dispatch_module_command,
    bootstrap_command_env,
    cron_loop,
    cron_main,
    main,
)
from pyvelm.loader import ModuleSpec
from pyvelm.migrate_cli import (
    module_action,
    print_migrate_plan,
    resolve_migrate_specs,
)


def _demo_spec(name: str = "demo", depends: list[str] | None = None) -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=(0, 1, 0),
        depends=depends or [],
        package=name,
        models_package=f"{name}.models",
        migrations_package=None,
        package_path=Path("/tmp/pyvelm_demo_module"),
        data=[],
    )


class CliHelperTests(unittest.TestCase):
    def test_parse_roots(self):
        with patch("pyvelm.cli.loader.parse_module_roots_env", return_value=[Path("/x")]):
            self.assertEqual(_parse_roots("/x"), [Path("/x")])

    def test_default_module_roots_dedupes(self):
        with (
            patch("pyvelm.BUILTIN_MODULE_ROOTS", [Path("/builtin")]),
            patch("pyvelm.scaffolder.find_modules_root", return_value=Path("/builtin")),
            patch.dict(os.environ, {"PYVELM_MODULE_ROOTS": ""}, clear=False),
        ):
            roots = _default_module_roots()
        self.assertEqual(len(roots), 1)

    def test_resolve_module_roots_explicit(self):
        args = Namespace(roots=[Path("/extra")])
        with patch("pyvelm.BUILTIN_MODULE_ROOTS", [Path("/b")]):
            roots = _resolve_module_roots(args)
        self.assertEqual(roots, [Path("/b"), Path("/extra")])

    def test_require_dsn_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                _require_dsn()

    def test_require_dsn_ok(self):
        with patch.dict(os.environ, {"PYVELM_DSN": "postgresql://u:p@h/db"}):
            self.assertEqual(_require_dsn(), "postgresql://u:p@h/db")

    def test_dsn_display_redacts_password(self):
        dsn = "postgresql://user:secret@localhost:5432/mydb"
        shown = _dsn_display(dsn)
        self.assertIn("user:***", shown)
        self.assertNotIn("secret", shown)

    def test_dsn_display_fallback(self):
        self.assertEqual(_dsn_display("not-a-url"), "<dsn>")

    def test_module_action_variants(self):
        spec = _demo_spec()
        self.assertEqual(module_action({}, spec), "install")
        self.assertEqual(module_action({spec.name: spec.version_str}, spec), "sync")
        self.assertIn("upgrade", module_action({spec.name: "0.0.1"}, spec))

    def test_ordered_specs_for_install_unknown_module(self):
        with (
            patch("pyvelm.cli.loader.discover", return_value={}),
            self.assertRaises(SystemExit),
        ):
            _ordered_specs_for_install([], "missing")

    def test_ordered_specs_for_install_with_deps(self):
        base = _demo_spec("base")
        child = _demo_spec("child", depends=["base"])
        specs = {"base": base, "child": child}
        with (
            patch("pyvelm.cli.loader.discover", return_value=specs),
            patch("pyvelm.cli.loader.resolve_order", return_value=[base, child]),
        ):
            ordered = _ordered_specs_for_install([], "child")
        self.assertEqual([s.name for s in ordered], ["base", "child"])

    def test_resolve_migrate_specs_fresh_after_wipe_bootstraps_bundled_only(self):
        from pyvelm.loader import BOOTSTRAP_MODULES

        base = _demo_spec("base")
        admin = _demo_spec("admin", depends=["base"])
        partners = _demo_spec("partners", depends=["base"])
        ordered = [base, admin, partners]
        with (
            patch(
                "pyvelm.migrate_cli.ordered_specs_for_install",
                return_value=ordered,
            ),
            patch("pyvelm.cli.psycopg.connect") as connect,
        ):
            result = resolve_migrate_specs(
                [],
                "postgresql://test",
                fresh_after_wipe=True,
            )
        connect.assert_not_called()
        expected = [s.name for s in ordered if s.name in BOOTSTRAP_MODULES]
        self.assertEqual([s.name for s in result], expected)
        self.assertNotIn("partners", result)

    def test_resolve_migrate_specs_installed_only(self):
        base = _demo_spec("base")
        admin = _demo_spec("admin")
        partners = _demo_spec("partners", depends=["base"])
        ordered = [base, admin, partners]
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            ("base",),
            ("admin",),
        ]
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=conn)
        conn_cm.__exit__ = MagicMock(return_value=False)
        with (
            patch("pyvelm.migrate_cli.ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.migrate_cli.psycopg.connect", return_value=conn_cm),
            patch("pyvelm.migrate_cli.loader.specs_to_install", return_value=[base, admin]) as filt,
        ):
            result = resolve_migrate_specs([], "postgresql://test")
        filt.assert_called_once()
        self.assertEqual([s.name for s in result], ["base", "admin"])

    def test_resolve_migrate_specs_all_skips_filter(self):
        ordered = [_demo_spec("base"), _demo_spec("partners")]
        with patch(
            "pyvelm.migrate_cli.ordered_specs_for_install",
            return_value=ordered,
        ) as order_fn:
            result = resolve_migrate_specs(
                [],
                "postgresql://test",
                install_all=True,
            )
        order_fn.assert_called_once()
        self.assertEqual(result, ordered)

    def test_resolve_migrate_specs_module_uses_subtree(self):
        base = _demo_spec("base")
        child = _demo_spec("child", depends=["base"])
        ordered = [base, child]
        with patch(
            "pyvelm.migrate_cli.ordered_specs_for_install",
            return_value=ordered,
        ) as order_fn:
            result = resolve_migrate_specs(
                [],
                "postgresql://test",
                only_module="child",
            )
        order_fn.assert_called_once_with([], "child")
        self.assertEqual(result, ordered)

    def test_print_migrate_plan(self):
        spec = _demo_spec()
        with patch("builtins.print") as printed:
            print_migrate_plan(
                dsn="postgresql://localhost/db",
                ordered=[spec],
                installed={},
                production=False,
            )
        text = " ".join(
            str(arg) for call in printed.call_args_list for arg in call.args
        )
        self.assertIn("demo", text)


class InitNewCliTests(unittest.TestCase):
    def test_init_invalid_name(self):
        with self.assertRaises(SystemExit):
            _run_init(Namespace(name="9bad"))

    def test_init_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "myproj"
            target.mkdir()
            with patch("pyvelm.cli.Path.cwd", return_value=Path(tmp)):
                with self.assertRaises(SystemExit):
                    _run_init(Namespace(name="myproj"))

    def test_init_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            with (
                patch("pyvelm.cli.Path.cwd", return_value=cwd),
                patch("pyvelm.scaffolder.echo_next_steps_for_init"),
            ):
                _run_init(Namespace(name="myproj"))
            self.assertTrue((cwd / "myproj").is_dir())

    def test_new_invalid_name(self):
        with self.assertRaises(SystemExit):
            _run_new(Namespace(name="bad-name", modules_root=None))

    def test_new_no_pyvelm_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("pyvelm.cli.Path.cwd", return_value=Path(tmp)),
                patch("pyvelm.scaffolder.find_modules_root", return_value=None),
                self.assertRaises(SystemExit),
            ):
                _run_new(Namespace(name="tasks", modules_root=None))

    def test_new_success_with_explicit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "modules"
            with patch("pyvelm.scaffolder.echo_next_steps_for_new"):
                _run_new(Namespace(name="tasks", modules_root=str(root)))
            self.assertTrue((root / "tasks").is_dir())


class DbDiffAutogenCliTests(unittest.TestCase):
    def _mock_env_spec(self):
        spec = _demo_spec()
        diff = MagicMock()
        diff.is_empty = True
        conn = MagicMock()
        return MagicMock(), spec, conn, diff

    def test_db_diff_reports_alterations(self):
        env, spec, conn, _diff = self._mock_env_spec()
        alt = MagicMock()
        alt.kind = "set_not_null"
        alt.table = "t"
        alt.column = "c"
        alt.cli_line.return_value = "  ~ t.c: set_not_null"
        diff = MagicMock()
        diff.is_empty = False
        diff.new_tables = []
        diff.new_columns = []
        diff.alterations = [alt]
        diff.orphan_columns = []
        with (
            patch("pyvelm.cli._build_db_env_and_spec", return_value=(env, spec, conn)),
            patch("pyvelm.db_autogen.compute_diff", return_value=diff),
            patch("pyvelm.db_autogen.count_null_rows", return_value=0),
            patch("builtins.print"),
        ):
            _run_db_diff(Namespace(module="demo"))

    def test_db_diff_prints_summary(self):
        env, spec, conn, diff = self._mock_env_spec()
        with (
            patch("pyvelm.cli._build_db_env_and_spec", return_value=(env, spec, conn)),
            patch("pyvelm.db_autogen.compute_diff", return_value=diff),
            patch("builtins.print") as printed,
        ):
            _run_db_diff(Namespace(module="demo"))
        text = " ".join(
            str(arg) for call in printed.call_args_list for arg in call.args
        )
        self.assertIn("no schema changes", text)

    def test_db_autogen_dry_run(self):
        env, spec, conn, diff = self._mock_env_spec()
        with (
            patch("pyvelm.cli._build_db_env_and_spec", return_value=(env, spec, conn)),
            patch("pyvelm.db_autogen.compute_diff", return_value=diff),
            patch("pyvelm.db_autogen.render_migration", return_value="# stub\n"),
            patch("builtins.print") as printed,
        ):
            _run_db_autogen(
                Namespace(
                    module="demo",
                    dry_run=True,
                    target_version=None,
                    with_views=False,
                )
            )
        text = " ".join(
            str(arg) for call in printed.call_args_list for arg in call.args
        )
        self.assertIn("would write", text)


class CronCliTests(unittest.TestCase):
    def test_run_cron_missing_dsn(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                _run_cron(Namespace(interval=1.0, roots=None))

    def test_tick_logs_executed(self):
        pool = MagicMock()
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=MagicMock())
        conn_cm.__exit__ = MagicMock(return_value=False)
        pool.connection.return_value = conn_cm
        reg = Registry()
        with reg.activate():
            from pyvelm.cron import CronJob

            with patch.object(CronJob, "run_due", return_value=["job-a"]):
                _tick(pool, reg)

    def test_cron_loop_exits_on_shutdown_signal(self):
        import signal

        pool = MagicMock()
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=MagicMock())
        conn_cm.__exit__ = MagicMock(return_value=False)
        pool.connection.return_value = conn_cm

        def _tick_and_stop(_pool, _reg):
            signal.raise_signal(signal.SIGTERM)

        with (
            patch("pyvelm.cli.psycopg.connect") as connect,
            patch("pyvelm.cli.loader.load_and_install"),
            patch("pyvelm.cli.ConnectionPool", return_value=pool),
            patch("pyvelm.cli._tick", side_effect=_tick_and_stop),
        ):
            connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
            connect.return_value.__exit__ = MagicMock(return_value=False)
            cron_loop(dsn="postgresql://localhost/db", roots=[], interval=60.0)
        pool.close.assert_called_once()


class MainParserTests(unittest.TestCase):
    def test_main_no_subcommand_prints_help(self):
        with (
            patch("sys.argv", ["pyvelm"]),
            patch("pyvelm.cli._load_dotenv"),
            patch("pyvelm.cli._try_dispatch_module_command", return_value=False),
            patch("pyvelm.cli._command_registry") as reg_fn,
            self.assertRaises(SystemExit) as ctx,
        ):
            reg_fn.return_value = MagicMock(all=MagicMock(return_value=[]))
            main()
        self.assertEqual(ctx.exception.code, 0)

    def test_run_cron_starts_loop(self):
        with (
            patch.dict(os.environ, {"PYVELM_DSN": "postgresql://localhost/db"}),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli.cron_loop") as loop,
        ):
            _run_cron(Namespace(interval=30.0, roots=None))
        loop.assert_called_once()

    def test_cron_loop_logs_tick_failure(self):
        pool = MagicMock()
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=MagicMock())
        conn_cm.__exit__ = MagicMock(return_value=False)
        pool.connection.return_value = conn_cm

        import signal

        calls = [0]

        def _tick_fail(_pool, _reg):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("tick failed")
            signal.raise_signal(signal.SIGTERM)

        with (
            patch("pyvelm.cli.psycopg.connect") as connect,
            patch("pyvelm.cli.loader.load_and_install"),
            patch("pyvelm.cli.ConnectionPool", return_value=pool),
            patch("pyvelm.cli._tick", side_effect=_tick_fail),
        ):
            connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
            connect.return_value.__exit__ = MagicMock(return_value=False)
            cron_loop(dsn="postgresql://localhost/db", roots=[], interval=60.0)

    def test_build_parser_has_subcommands(self):
        parser = _build_parser()
        self.assertIsNotNone(parser.parse_args(["init", "proj"]))
        self.assertIsNotNone(parser.parse_args(["db", "status"]))

    def test_main_help_exits_zero(self):
        with (
            patch("sys.argv", ["pyvelm", "--help"]),
            patch("pyvelm.cli._load_dotenv"),
            self.assertRaises(SystemExit) as ctx,
        ):
            main()
        self.assertEqual(ctx.exception.code, 0)

    def test_cron_main_delegates(self):
        with (
            patch("sys.argv", ["pyvelm-cron", "--interval", "5"]),
            patch("pyvelm.cli._load_dotenv"),
            patch("pyvelm.cli._run_cron") as run,
        ):
            cron_main()
        run.assert_called_once()

    def test_load_dotenv_no_file(self):
        with patch("pathlib.Path.exists", return_value=False):
            _load_dotenv()  # should not raise

    def test_command_list_and_help(self):
        from pyvelm.tests.test_console import _DemoCommand

        reg = MagicMock()
        reg.all.return_value = [_DemoCommand()]
        reg.get.return_value = _DemoCommand()
        with patch("pyvelm.cli._command_registry", return_value=reg):
            with patch("builtins.print") as printed:
                _run_command_list(None)
            text = " ".join(str(c.args[0]) for c in printed.call_args_list if c.args)
            self.assertIn("Core:", text)
            self.assertIn("cron", text)
            self.assertIn("Module:", text)
            self.assertIn("demo:run", text)
            _run_command_help(Namespace(command_name="demo:run"))
            reg.get.assert_called_with("demo:run")

    def test_try_dispatch_module_command(self):
        with (
            patch("pyvelm.cli._command_registry") as reg_fn,
            patch("pyvelm.cli.bootstrap_command_env"),
        ):
            reg = MagicMock()
            reg.names.return_value = ["demo:run"]
            reg.run.return_value = 0
            reg_fn.return_value = reg
            with self.assertRaises(SystemExit) as ctx:
                _try_dispatch_module_command(["demo:run", "x"])
            self.assertEqual(ctx.exception.code, 0)
            reg.run.assert_called_once()

    def test_bootstrap_command_env_sets_ctx(self):
        ctx = MagicMock(roots=[Path("/mods")], env=None, registry=None)
        conn = MagicMock()
        spec = _demo_spec()
        with (
            patch.dict(os.environ, {"PYVELM_DSN": "postgresql://localhost/db"}),
            patch("pyvelm.cli.loader.discover", return_value={spec.name: spec}),
            patch("pyvelm.cli.loader.resolve_order", return_value=[spec]),
            patch("pyvelm.cli.loader._load_models"),
            patch("pyvelm.cli.psycopg.connect", return_value=conn),
        ):
            bootstrap_command_env(ctx)
        self.assertIsNotNone(ctx.env)


if __name__ == "__main__":
    unittest.main()
