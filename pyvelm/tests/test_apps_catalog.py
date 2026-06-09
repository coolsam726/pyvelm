"""Apps catalog upgrade detection and action buttons."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pathlib import Path

from pyvelm.env import Environment
from pyvelm.loader import BOOTSTRAP_MODULES, ModuleSpec
from pyvelm.registry import Registry
from pyvelm.render import (
    _apps_catalog,
    _manifest_reverse_dependents,
    _uninstall_blockers,
    sync_module_action,
    upgrade_module_action,
)


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
            patch(
                "pyvelm.render._uninstall_blockers",
                return_value=([], []),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertTrue(entry["version_upgrade"])
        self.assertTrue(entry["pending_migrations"])
        self.assertTrue(entry["needs_upgrade"])
        self.assertEqual(entry["state"], "to_upgrade")

    def test_schema_diff_sets_needs_sync_without_version_bump(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(True, "1 new column(s)"),
            ),
            patch(
                "pyvelm.render._uninstall_blockers",
                return_value=([], []),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["version_upgrade"])
        self.assertFalse(entry["pending_migrations"])
        self.assertFalse(entry["needs_upgrade"])
        self.assertTrue(entry["has_schema_diff"])
        self.assertTrue(entry["needs_sync"])
        self.assertEqual(entry["state"], "to_sync")
        self.assertEqual(entry["schema_diff_summary"], "1 new column(s)")

    def test_orphan_columns_do_not_set_needs_sync(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(False, ""),
            ),
            patch(
                "pyvelm.render._uninstall_blockers",
                return_value=([], []),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["needs_sync"])
        self.assertEqual(entry["state"], "installed")

    def test_installed_without_changes_shows_installed_state(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = self._env_with_installed([("partners", "0.1.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(False, ""),
            ),
            patch(
                "pyvelm.render._uninstall_blockers",
                return_value=([], []),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["needs_upgrade"])
        self.assertFalse(entry["needs_sync"])
        self.assertFalse(entry["pending_migrations"])
        self.assertEqual(entry["state"], "installed")

    def test_bootstrap_module_cannot_uninstall(self):
        env = self._env_with_installed([("base", "0.32.0")])
        blockers, reverse = _uninstall_blockers(env, [], "base", installed={"base"})
        self.assertIn("bootstrap", blockers[0].lower())
        self.assertEqual(reverse, [])

    def test_reverse_deps_block_uninstall(self):
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        partners = _spec("partners", version=(0, 4, 0))
        crm = _spec("crm")
        crm.depends = ["partners"]
        blockers, reverse = _uninstall_blockers(
            env,
            [],
            "partners",
            specs={"partners": partners, "crm": crm},
            installed={"partners", "crm"},
        )
        self.assertIn("crm", reverse)
        self.assertTrue(any("depended" in b for b in blockers))

    def test_demo_module_not_reverse_dep_of_super_chain_demo(self):
        """Module name ``demo`` must not false-match ``super_chain_demo*``."""
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        demo = _spec("demo")
        demo.depends = ["base", "partners", "partners_pro", "crm"]
        chain = _spec("super_chain_demo")
        chain.depends = ["base"]
        specs = {"demo": demo, "super_chain_demo": chain, "base": _spec("base")}
        reverse = _manifest_reverse_dependents(
            "super_chain_demo",
            specs,
            installed={"super_chain_demo", "base"},
        )
        self.assertNotIn("demo", reverse)

    def test_uninstalled_demo_not_reverse_dep_of_super_chain_demo(self):
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        demo = _spec("demo")
        demo.depends = ["base", "partners", "partners_pro", "crm"]
        chain = _spec("super_chain_demo")
        chain.depends = ["base"]
        blockers, reverse = _uninstall_blockers(
            env,
            [],
            "super_chain_demo",
            specs={"demo": demo, "super_chain_demo": chain},
            installed={"super_chain_demo"},
        )
        self.assertNotIn("demo", reverse)
        self.assertFalse(any("demo" in b for b in blockers))

    def test_super_chain_demo_catalog_installable_without_demo(self):
        example = Path(__file__).resolve().parents[2] / "examples" / "modules"
        demo_root = Path(__file__).resolve().parents[2] / "examples" / "modules_demo"
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        env.conn.execute.return_value.fetchall.return_value = [("base", "0.32.0")]
        with patch(
            "pyvelm.render._catalog_schema_diff_pending",
            return_value=(False, ""),
        ):
            catalog = _apps_catalog(env, [example, demo_root])
        by_name = {e["name"]: e for e in catalog}
        chain = by_name["super_chain_demo"]
        demo = by_name["demo"]
        self.assertEqual(chain["state"], "uninstalled")
        self.assertTrue(chain["can_install"])
        self.assertEqual(chain["install_blockers"], [])
        self.assertNotIn("demo", chain["reverse_deps"])
        self.assertEqual(demo["state"], "uninstalled")
        self.assertTrue(demo["can_install"])

    def test_inherit_extension_module_is_uninstallable(self):
        from pyvelm.loader import _load_models, discover

        example = Path(__file__).resolve().parents[2] / "examples" / "modules"
        specs = discover([example])
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        _load_models(specs["super_chain_demo"], env.registry)
        _load_models(specs["super_chain_demo_b"], env.registry)
        blockers, reverse = _uninstall_blockers(
            env,
            [example],
            "super_chain_demo_b",
            specs=specs,
            installed={"super_chain_demo", "super_chain_demo_b"},
        )
        self.assertFalse(blockers)
        self.assertEqual(reverse, [])

    def test_base_owner_blocked_while_extension_installed(self):
        from pyvelm.loader import _load_models, discover

        example = Path(__file__).resolve().parents[2] / "examples" / "modules"
        specs = discover([example])
        env = Environment(MagicMock(), registry=Registry(), uid=1)
        _load_models(specs["super_chain_demo"], env.registry)
        _load_models(specs["super_chain_demo_a"], env.registry)
        blockers, reverse = _uninstall_blockers(
            env,
            [example],
            "super_chain_demo",
            specs=specs,
            installed={"super_chain_demo", "super_chain_demo_a"},
        )
        self.assertTrue(
            any("Extended by" in b or "depended" in b for b in blockers),
            blockers,
        )
        self.assertIn("super_chain_demo_a", reverse)

    def test_catalog_marks_bootstrap_as_protected(self):
        spec = _spec("base", version=(0, 32, 0))
        env = self._env_with_installed([("base", "0.32.0")])
        with (
            patch("pyvelm.loader.discover", return_value={"base": spec}),
            patch(
                "pyvelm.render._catalog_schema_diff_pending",
                return_value=(False, ""),
            ),
        ):
            catalog = _apps_catalog(env, [MagicMock()])
        entry = catalog[0]
        self.assertFalse(entry["can_uninstall"])
        self.assertTrue(entry["uninstall_blockers"])
        self.assertIn("base", BOOTSTRAP_MODULES)


class AppsActionMessageTests(unittest.TestCase):
    def test_upgrade_and_sync_messages_differ(self):
        spec = _spec("partners", version=(0, 2, 0))
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

    def test_upgrade_noop_when_no_pending_migrations(self):
        spec = _spec("partners", version=(0, 1, 0))
        env = MagicMock()
        env.registry = Registry()
        with (
            patch("pyvelm.loader.discover", return_value={"partners": spec}),
            patch("pyvelm.loader._installed_version", return_value=(0, 1, 0)),
            patch("pyvelm.loader.reload_installed_models") as reload_models,
            patch("pyvelm.loader.install") as install,
        ):
            result = upgrade_module_action(env, [], "partners")
        self.assertEqual(result["upgraded"], [])
        self.assertIn("no pending migrations", result["message"].lower())
        reload_models.assert_not_called()
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
