"""CLI tests for ``pyvelm db migrate``, ``migrate-fresh``, and ``status``."""

from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from pyvelm.cli import (
    _confirm_migrate_fresh,
    _run_db_migrate,
    _run_db_migrate_fresh,
    _run_db_status,
)
from pyvelm.loader import ModuleSpec


def _demo_spec(name: str = "demo") -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=(0, 1, 0),
        depends=[],
        package=name,
        models_package=f"{name}.models",
        migrations_package=None,
        package_path=None,
        data=[],
    )


def _mock_conn_cm():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    conn_cm = MagicMock()
    conn_cm.__enter__ = MagicMock(return_value=conn)
    conn_cm.__exit__ = MagicMock(return_value=False)
    return conn_cm


class DbMigrateCliTests(unittest.TestCase):
    def test_migrate_loads_models_and_installs(self):
        spec = _demo_spec()
        ordered = [spec]
        install_results = [
            {
                "name": "demo",
                "schema": "schema: 1 column(s)",
                "views": "2 view(s)",
                "menus": "1 menu(s)",
            }
        ]

        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.cli.loader._load_models") as load_models,
            patch("pyvelm.cli.loader.install", return_value=install_results) as install,
            patch("pyvelm.cli.psycopg.connect", return_value=_mock_conn_cm()),
            patch("pyvelm.cli.Registry"),
            patch("pyvelm.cli.Environment"),
        ):
            _run_db_migrate(Namespace(roots=None))

        load_models.assert_called_once()
        install.assert_called_once()

    def test_status_prints_not_installed(self):
        spec = ModuleSpec(
            name="tasks",
            version=(0, 2, 0),
            depends=[],
            package="tasks",
            models_package="tasks.models",
            migrations_package=None,
            package_path=None,
            data=[],
        )
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=conn)
        conn_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli.loader.discover", return_value={"tasks": spec}),
            patch("pyvelm.cli.loader.resolve_order", return_value=[spec]),
            patch("pyvelm.cli.psycopg.connect", return_value=conn_cm),
            patch("pyvelm.cli.Registry"),
            patch("pyvelm.cli.Environment") as env_cls,
        ):
            env_cls.return_value.conn = conn
            with patch("builtins.print") as printed:
                _run_db_status(Namespace(roots=None))

        text = " ".join(str(c[0][0]) for c in printed.call_args_list)
        self.assertIn("tasks", text)
        self.assertIn("not installed", text)


class DbMigrateFreshCliTests(unittest.TestCase):
    def test_production_aborts_without_confirmation(self):
        ordered = [_demo_spec("base")]
        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.cli.psycopg.connect", return_value=_mock_conn_cm()),
            patch("pyvelm.runtime.is_production", return_value=True),
            patch("pyvelm.runtime.get_runtime_env", return_value="production"),
            patch("builtins.input", return_value="no"),
        ):
            with self.assertRaises(SystemExit):
                _run_db_migrate_fresh(
                    Namespace(
                        roots=None,
                        only_module=None,
                        yes=False,
                        dry_run=False,
                    )
                )

    def test_production_runs_with_yes(self):
        ordered = [_demo_spec("base")]
        install_results = [{"name": "base", "schema": "ok", "views": "", "menus": ""}]
        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.cli.loader.install", return_value=install_results) as install,
            patch("pyvelm.cli.psycopg.connect", return_value=_mock_conn_cm()),
            patch("pyvelm.runtime.is_production", return_value=True),
            patch("pyvelm.runtime.get_runtime_env", return_value="production"),
        ):
            _run_db_migrate_fresh(
                Namespace(
                    roots=None,
                    only_module=None,
                    yes=True,
                    dry_run=False,
                )
            )
            install.assert_called_once()

    def test_dry_run_does_not_install(self):
        ordered = [_demo_spec()]
        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.cli.loader.install") as install,
            patch("pyvelm.cli.psycopg.connect", return_value=_mock_conn_cm()),
            patch("pyvelm.runtime.is_production", return_value=False),
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
        ):
            _run_db_migrate_fresh(
                Namespace(
                    roots=None,
                    only_module=None,
                    yes=False,
                    dry_run=True,
                )
            )
            install.assert_not_called()

    def test_confirm_phrase_exact(self):
        with patch("builtins.input", return_value="migrate-fresh"):
            _confirm_migrate_fresh(production=True, yes=False)
        with patch("builtins.input", return_value="wrong"):
            with self.assertRaises(SystemExit):
                _confirm_migrate_fresh(production=True, yes=False)


if __name__ == "__main__":
    unittest.main()
