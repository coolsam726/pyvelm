"""CLI tests for ``pyvelm migrate``, ``db migrate-fresh``, and ``db status``."""

from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from pyvelm.cli import (
    _run_db_migrate_fresh,
    _run_db_migrate_shim,
    _run_db_nuke,
    _run_db_status,
)
from pyvelm.loader import ModuleSpec
from pyvelm.migrate_cli import (
    confirm_migrate_fresh,
    drop_schema_contents,
    resolve_migrate_specs,
    run_migrate_fresh,
    run_migrate_reset,
)


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


def _mock_database():
    db = MagicMock()
    db.connect.return_value = _mock_conn_cm()
    return db


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
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=ordered,
            ) as resolve_specs,
            patch("pyvelm.migrate_cli.loader._load_models") as load_models,
            patch(
                "pyvelm.migrate_cli.loader.install",
                return_value=install_results,
            ) as install,
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.migrate_cli.Registry"),
            patch("pyvelm.migrate_cli.Environment"),
        ):
            from pyvelm.migrate_cli import run_migrate

            run_migrate([], install_all=False, only_module=None)

        resolve_specs.assert_called_once()
        load_models.assert_called_once()
        install.assert_called_once()

    def test_migrate_all_passes_install_all(self):
        spec = _demo_spec()
        ordered = [spec]
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=ordered,
            ) as resolve_specs,
            patch("pyvelm.migrate_cli.loader.install", return_value=[]),
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.migrate_cli.Registry"),
            patch("pyvelm.migrate_cli.Environment"),
            patch("pyvelm.migrate_cli.loader._load_models"),
        ):
            from pyvelm.migrate_cli import run_migrate

            run_migrate([], install_all=True, only_module=None)
        resolve_specs.assert_called_once_with(
            [],
            "postgresql://test",
            only_module=None,
            install_all=True,
        )

    def test_db_migrate_shim_delegates(self):
        with (
            patch("pyvelm.cli.run_migrate") as migrate,
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("sys.stderr", MagicMock()),
        ):
            _run_db_migrate_shim(
                Namespace(roots=None, all=True, only_module="partners")
            )
        migrate.assert_called_once_with(
            [],
            install_all=True,
            only_module="partners",
            database_key=None,
        )

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
            patch("pyvelm.database.create_database_from_dsn", return_value=_mock_database()),
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
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=ordered,
            ),
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.runtime.is_production", return_value=True),
            patch("pyvelm.runtime.get_runtime_env", return_value="production"),
            patch("builtins.input", return_value="no"),
        ):
            with self.assertRaises(SystemExit):
                _run_db_migrate_fresh(
                    Namespace(
                        roots=None,
                        only_module=None,
                        all=False,
                        yes=False,
                        dry_run=False,
                    )
                )

    def test_production_runs_with_yes(self):
        ordered = [_demo_spec("base")]
        install_results = [{"name": "base", "schema": "ok", "views": "", "menus": ""}]
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=ordered,
            ),
            patch(
                "pyvelm.migrate_cli.loader.install",
                return_value=install_results,
            ) as install,
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.runtime.is_production", return_value=True),
            patch("pyvelm.runtime.get_runtime_env", return_value="production"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
        ):
            _run_db_migrate_fresh(
                Namespace(
                    roots=None,
                    only_module=None,
                    all=False,
                    yes=True,
                    dry_run=False,
                )
            )
            install.assert_called_once()

    def test_dry_run_does_not_install(self):
        ordered = [_demo_spec()]
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=ordered,
            ),
            patch("pyvelm.migrate_cli.loader.install") as install,
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.runtime.is_production", return_value=False),
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
        ):
            _run_db_migrate_fresh(
                Namespace(
                    roots=None,
                    only_module=None,
                    all=False,
                    yes=False,
                    dry_run=True,
                )
            )
            install.assert_not_called()

    def test_confirm_phrase_exact(self):
        with patch("builtins.input", return_value="migrate-fresh"):
            confirm_migrate_fresh(production=True, yes=False)
        with patch("builtins.input", return_value="wrong"):
            with self.assertRaises(SystemExit):
                confirm_migrate_fresh(production=True, yes=False)


class DbNukeCliTests(unittest.TestCase):
    """`db nuke` is the dev-only wrecking ball — make sure it refuses
    production, walks the schema/install flow correctly, and respects
    the typed confirmation."""

    def _args(self, *, yes: bool = True, schema: str = "public") -> Namespace:
        return Namespace(roots=None, yes=yes, schema=schema)

    def test_aborts_in_production(self):
        with patch("pyvelm.runtime.is_production", return_value=True):
            with self.assertRaises(SystemExit) as cm:
                _run_db_nuke(self._args())
        self.assertIn("production", str(cm.exception).lower())

    def test_drops_schema_then_reinstalls(self):
        ordered = [_demo_spec("base"), _demo_spec("admin")]
        install_results = [
            {"name": "base", "schema": "", "views": "", "menus": ""},
            {"name": "admin", "schema": "", "views": "", "menus": ""},
        ]
        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.migrate_cli.drop_schema_contents") as drop,
            patch("pyvelm.migrate_cli.loader.install", return_value=install_results) as install,
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.runtime.is_production", return_value=False),
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
        ):
            _run_db_nuke(self._args(yes=True, schema="public"))
            drop.assert_called_once()
            self.assertEqual(drop.call_args.args[1], "public")
            install.assert_called_once()

    def test_typed_confirmation_blocks_when_wrong(self):
        ordered = [_demo_spec("base")]
        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli._ordered_specs_for_install", return_value=ordered),
            patch("pyvelm.migrate_cli.drop_schema_contents") as drop,
            patch("pyvelm.migrate_cli.loader.install") as install,
            patch("pyvelm.migrate_cli.create_database_from_dsn", return_value=_mock_database()),
            patch("pyvelm.runtime.is_production", return_value=False),
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
            patch("builtins.input", return_value="wrong"),
        ):
            with self.assertRaises(SystemExit):
                _run_db_nuke(self._args(yes=False))
        drop.assert_not_called()
        install.assert_not_called()

    def test_drop_schema_contents_runs_drop_and_create(self):
        conn = MagicMock()
        conn.capabilities.name = "postgresql"
        drop_schema_contents(conn, "public")
        self.assertGreaterEqual(conn.execute.call_count, 2)
        sqls = [str(c.args[0]) for c in conn.execute.call_args_list]
        self.assertTrue(any("pg_advisory_lock" in s for s in sqls))
        self.assertTrue(any("pg_terminate_backend" in s for s in sqls))
        self.assertTrue(any("usename = current_user" in s for s in sqls))
        self.assertTrue(any("DROP SCHEMA" in s for s in sqls))
        self.assertTrue(any("CREATE SCHEMA" in s for s in sqls))
        self.assertTrue(any("pg_advisory_unlock" in s for s in sqls))


class MigrateColonCommandTests(unittest.TestCase):
    def test_migrate_reset_wipes_only(self):
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch("pyvelm.migrate_cli.guard_destructive_schema_command"),
            patch("pyvelm.migrate_cli.confirm_destructive_phrase"),
            patch("pyvelm.migrate_cli.wipe_schema") as wipe,
            patch("pyvelm.migrate_cli.loader.install") as install,
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
        ):
            run_migrate_reset([], yes=True, schema="public")
        wipe.assert_called_once_with("postgresql://test", "public")
        install.assert_not_called()

    def test_migrate_fresh_wipes_then_migrates(self):
        spec = _demo_spec("base")
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="postgresql://test"),
            patch("pyvelm.migrate_cli.guard_destructive_schema_command"),
            patch("pyvelm.migrate_cli.confirm_destructive_phrase"),
            patch(
                "pyvelm.migrate_cli.resolve_migrate_specs",
                return_value=[spec],
            ) as resolve,
            patch("pyvelm.migrate_cli.wipe_schema") as wipe,
            patch("pyvelm.migrate_cli.execute_db_install", return_value=[]) as migrate,
            patch("pyvelm.runtime.get_runtime_env", return_value="development"),
        ):
            run_migrate_fresh(
                [],
                yes=True,
                schema="public",
                install_all=False,
                only_module=None,
            )
        resolve.assert_called_once_with(
            [],
            "postgresql://test",
            only_module=None,
            install_all=False,
            fresh_after_wipe=True,
        )
        wipe.assert_called_once()
        migrate.assert_called_once()

    def test_migrate_reset_aborts_in_production(self):
        with patch("pyvelm.runtime.is_production", return_value=True):
            with self.assertRaises(SystemExit) as cm:
                run_migrate_reset([], yes=True, schema="public")
        self.assertIn("production", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
