"""Apps catalog upgrade detection and action buttons."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.env import Environment
from pyvelm.loader import ModuleSpec
from pyvelm.registry import Registry
from pyvelm.render import _apps_catalog, sync_module_action, upgrade_module_action


def _spec(name: str, version=(0, 2, 0)) -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=version,
        depends=[],
        package=name,
        models_package=f"{name}.models",
        migrations_package=None,
        package_path=None,
        data=[],
    )


class AppsCatalogUpgradeTests(unittest.TestCase):
    def _env_with_installed(self, rows: list[tuple[str, str]]) -> Environment:
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = rows
        return Environment(conn, registry=Registry(), uid=1)

    def test_version_bump_sets_needs_upgrade(self):
        spec = _spec("partners")
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(False, ""),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertTrue(entry["version_upgrade"])
        self.assertTrue(entry["needs_upgrade"])
        self.assertEqual(entry["state"], "to_upgrade")

    def test_schema_diff_sets_needs_upgrade_without_version_bump(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(True, "1 new column(s)"),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["version_upgrade"])
        self.assertTrue(entry["has_schema_diff"])
        self.assertTrue(entry["needs_upgrade"])
        self.assertEqual(entry["schema_diff_summary"], "1 new column(s)")

    def test_installed_without_changes_has_sync_only(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(False, ""),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["needs_upgrade"])
        self.assertEqual(entry["state"], "installed")


class AppsActionMessageTests(unittest.TestCase):
    def test_upgrade_and_sync_messages_differ(self):
        spec = _spec("partners")
        env = MagicMock()
        env.registry = Registry()
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch("pyvelm.loader._installed_version", return_value=(0, 1, 0)),
            patch("pyvelm.loader.reload_installed_models"),
            patch(
                "pyvelm.loader.install",
                return_value=[{"name": "partners", "schema": "ok", "views": "", "menus": ""}],
            ),
        ):
            up = upgrade_module_action(env, [], "partners")
            sync = sync_module_action(env, [], "partners")
        self.assertIn("Upgraded partners", up["message"])
        self.assertIn("Synced partners", sync["message"])


if __name__ == "__main__":
    unittest.main()
