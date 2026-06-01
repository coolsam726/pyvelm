"""Coverage tests for ``pyvelm.migrate_cli`` helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pyvelm.loader import ModuleSpec
from pyvelm.migrate_cli import (
    _drop_schema_with_retry,
    _nuke_attempts,
    confirm_destructive_phrase,
    confirm_migrate_fresh,
    module_action,
    ordered_specs_for_install,
    read_installed_versions,
    resolve_migrate_specs,
    run_db_seed,
    wipe_schema,
)


def _spec(
    name: str,
    *,
    depends=None,
    version=(0, 1, 0),
    seeders=None,
) -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=version,
        depends=depends or [],
        package=name,
        models_package=f"{name}.models",
        migrations_package=None,
        package_path=None,
        data=[],
        seeders=list(seeders or []),
    )


class MigrateCliHelperTests(unittest.TestCase):
    def test_read_installed_versions_swallows_errors(self):
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("no table")
        self.assertEqual(read_installed_versions(conn), {})

    def test_module_action_variants(self):
        spec = _spec("demo")
        self.assertEqual(module_action({}, spec), "install")
        self.assertEqual(module_action({"demo": "0.1.0"}, spec), "sync")
        self.assertIn("upgrade", module_action({"demo": "0.0.1"}, spec))

    def test_ordered_specs_missing_module_exits(self):
        with patch("pyvelm.migrate_cli.loader.discover", return_value={}):
            with self.assertRaises(SystemExit):
                ordered_specs_for_install([Path("/mods")], "missing")

    def test_ordered_specs_missing_dependency_exits(self):
        specs = {"child": _spec("child", depends=["parent"])}
        with patch("pyvelm.migrate_cli.loader.discover", return_value=specs):
            with self.assertRaises(SystemExit):
                ordered_specs_for_install([Path("/mods")], "child")

    def test_ordered_specs_all_discovered_when_no_only_module(self):
        specs = {"a": _spec("a"), "b": _spec("b")}
        ordered = [_spec("a"), _spec("b")]
        with patch("pyvelm.migrate_cli.loader.discover", return_value=specs), patch(
            "pyvelm.migrate_cli.loader.resolve_order", return_value=ordered
        ) as resolve_order:
            out = ordered_specs_for_install([Path("/mods")], None)
        resolve_order.assert_called_once_with(specs)
        self.assertEqual(len(out), 2)

    def test_confirm_migrate_fresh_non_production_returns(self):
        confirm_migrate_fresh(production=False, yes=False)

    def test_drop_schema_with_retry_exhausted_raises(self):
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("lock timeout")
        with patch("time.sleep"):
            with self.assertRaises(RuntimeError):
                _drop_schema_with_retry(conn, "public", attempts=2)

    def test_ordered_specs_dedupes_dependency_walk(self):
        specs = {
            "base": _spec("base"),
            "addon": _spec("addon", depends=["base"]),
        }
        with patch("pyvelm.migrate_cli.loader.discover", return_value=specs), patch(
            "pyvelm.migrate_cli.loader.resolve_order",
            return_value=[specs["base"], specs["addon"]],
        ):
            out = ordered_specs_for_install([Path("/mods")], "addon")
        self.assertEqual([s.name for s in out], ["base", "addon"])

    def test_ordered_specs_skips_revisited_dependency(self):
        specs = {
            "base": _spec("base"),
            "mid": _spec("mid", depends=["base"]),
            "leaf": _spec("leaf", depends=["mid", "base"]),
        }
        with patch("pyvelm.migrate_cli.loader.discover", return_value=specs), patch(
            "pyvelm.migrate_cli.loader.resolve_order",
            return_value=[specs["base"], specs["mid"], specs["leaf"]],
        ):
            out = ordered_specs_for_install([Path("/mods")], "leaf")
        self.assertEqual([s.name for s in out], ["base", "mid", "leaf"])

    def test_resolve_migrate_specs_uses_specs_to_install(self):
        specs = [_spec("a"), _spec("b")]
        with (
            patch(
                "pyvelm.migrate_cli.ordered_specs_for_install", return_value=specs
            ),
            patch("pyvelm.migrate_cli.create_database_from_dsn") as create_db,
            patch("pyvelm.migrate_cli.loader.specs_to_install", return_value=[specs[0]]),
        ):
            db = MagicMock()
            conn = MagicMock()
            db.connect.return_value.__enter__ = MagicMock(return_value=conn)
            db.connect.return_value.__exit__ = MagicMock(return_value=False)
            create_db.return_value = db
            out = resolve_migrate_specs([Path("/mods")], "sqlite:///:memory:")
        self.assertEqual([s.name for s in out], ["a"])

    def test_confirm_migrate_fresh_yes_on_production(self):
        with patch("pyvelm.migrate_cli.print") as printed:
            confirm_migrate_fresh(production=True, yes=True)
        printed.assert_called()

    def test_drop_schema_with_retry_reraises_non_lock_errors(self):
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("syntax error")
        with self.assertRaises(RuntimeError):
            _drop_schema_with_retry(conn, "public", attempts=1)

    def test_run_db_seed_no_seeders_on_spec(self):
        spec = _spec("demo", seeders=[])
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="sqlite:///:memory:"),
            patch("pyvelm.migrate_cli.ordered_specs_for_install", return_value=[spec]),
        ):
            run_db_seed([Path("/mods")], only_module="demo")

    def test_ordered_specs_only_module_closure(self):
        specs = {
            "base": _spec("base"),
            "addon": _spec("addon", depends=["base"]),
            "other": _spec("other"),
        }
        with patch("pyvelm.migrate_cli.loader.discover", return_value=specs), patch(
            "pyvelm.migrate_cli.loader.resolve_order",
            return_value=[specs["base"], specs["addon"], specs["other"]],
        ):
            out = ordered_specs_for_install([Path("/mods")], "addon")
        self.assertEqual([s.name for s in out], ["base", "addon"])

    def test_resolve_migrate_specs_fresh_after_wipe(self):
        specs = [_spec("base"), _spec("other")]
        with patch(
            "pyvelm.migrate_cli.ordered_specs_for_install", return_value=specs
        ), patch("pyvelm.migrate_cli.loader.BOOTSTRAP_MODULES", {"base"}):
            out = resolve_migrate_specs(
                [Path("/mods")],
                "sqlite:///:memory:",
                fresh_after_wipe=True,
            )
        self.assertEqual([s.name for s in out], ["base"])

    def test_nuke_attempts_serverless_and_invalid(self):
        with patch("pyvelm.migrate_cli.uses_serverless_schema_wipe", return_value=False):
            self.assertEqual(_nuke_attempts(), 1)
        with patch(
            "pyvelm.migrate_cli.uses_serverless_schema_wipe", return_value=True
        ), patch.dict("os.environ", {"PYVELM_NUKE_ATTEMPTS": "nope"}):
            self.assertEqual(_nuke_attempts(), 6)

    def test_drop_schema_with_retry_lock_errors(self):
        conn = MagicMock()
        conn.execute.side_effect = [
            RuntimeError("lock timeout"),
            None,
            None,
            None,
            None,
        ]
        with patch("time.sleep"):
            _drop_schema_with_retry(conn, "public", attempts=2)
        self.assertGreaterEqual(conn.execute.call_count, 2)

    def test_confirm_migrate_fresh_aborts_on_eof(self):
        with patch("pyvelm.migrate_cli.input", side_effect=EOFError):
            with self.assertRaises(SystemExit):
                confirm_migrate_fresh(production=True, yes=False)

    def test_confirm_destructive_phrase_mismatch(self):
        with patch("pyvelm.migrate_cli.input", return_value="nope"):
            with self.assertRaises(SystemExit):
                confirm_destructive_phrase(
                    phrase="reset", yes=False, preamble="warn"
                )

    def test_run_db_seed_only_module(self):
        spec = _spec("geo_data", seeders=["geo:Seeder"])
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="sqlite:///:memory:"),
            patch(
                "pyvelm.migrate_cli.ordered_specs_for_install", return_value=[spec]
            ),
            patch("pyvelm.migrate_cli.create_database_from_dsn") as create_db,
            patch("pyvelm.migrate_cli.loader._load_models"),
            patch("pyvelm.migrate_cli.loader._run_module_seeders") as run_seeders,
        ):
            db = MagicMock()
            conn = MagicMock()
            db.connect.return_value.__enter__ = MagicMock(return_value=conn)
            db.connect.return_value.__exit__ = MagicMock(return_value=False)
            create_db.return_value = db
            run_db_seed([Path("/mods")], only_module="geo_data")
        run_seeders.assert_called_once()

    def test_run_db_seed_all_installed(self):
        spec = _spec("demo", seeders=["demo:Seeder"])
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="sqlite:///:memory:"),
            patch("pyvelm.migrate_cli.loader.discover", return_value={"demo": spec}),
            patch(
                "pyvelm.migrate_cli.loader.resolve_order", return_value=[spec]
            ),
            patch(
                "pyvelm.migrate_cli.read_installed_versions", return_value={"demo"}
            ),
            patch("pyvelm.migrate_cli.create_database_from_dsn") as create_db,
            patch("pyvelm.migrate_cli.loader._load_models"),
            patch("pyvelm.migrate_cli.loader._run_module_seeders") as run_seeders,
        ):
            db = MagicMock()
            conn = MagicMock()
            db.connect.return_value.__enter__ = MagicMock(return_value=conn)
            db.connect.return_value.__exit__ = MagicMock(return_value=False)
            create_db.return_value = db
            run_db_seed([Path("/mods")])
        run_seeders.assert_called_once()

    def test_run_db_seed_nothing_to_seed(self):
        with (
            patch("pyvelm.migrate_cli.require_dsn", return_value="sqlite:///:memory:"),
            patch("pyvelm.migrate_cli.loader.discover", return_value={}),
            patch("pyvelm.migrate_cli.create_database_from_dsn"),
            patch("pyvelm.migrate_cli.read_installed_versions", return_value=set()),
        ):
            run_db_seed([Path("/mods")])

    def test_wipe_schema_non_postgres_uses_reset(self):
        db = MagicMock()
        db.capabilities.supports_drop_schema = False
        conn = MagicMock()
        db.connect.return_value.__enter__ = MagicMock(return_value=conn)
        db.connect.return_value.__exit__ = MagicMock(return_value=False)
        with patch(
            "pyvelm.migrate_cli.create_database_from_dsn", return_value=db
        ), patch("pyvelm.migrate_cli.reset_schema") as reset:
            wipe_schema("sqlite:///tmp/x.db", "public")
        reset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
