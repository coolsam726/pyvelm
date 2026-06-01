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
    wipe_schema,
)


def _spec(name: str, *, depends=None, version=(0, 1, 0)) -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=version,
        depends=depends or [],
        package=name,
        models_package=f"{name}.models",
        migrations_package=None,
        package_path=None,
        data=[],
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
