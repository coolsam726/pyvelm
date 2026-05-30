"""Loader bootstrap install policy (bundled pyvelm/modules on fresh DB)."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.loader import BOOTSTRAP_MODULES, ModuleSpec, specs_to_install
from pyvelm.render import install_module_action
from pyvelm.tests.support.db import DatabaseTestCase, reset_database


def _spec(name: str, depends: list[str] | None = None) -> ModuleSpec:
    return ModuleSpec(
        name=name,
        version=(0, 1, 0),
        depends=depends or [],
        package=name,
        models_package=f"{name}.models",
        migrations_package=f"{name}.migrations",
    )


class SpecsToInstallTests(unittest.TestCase):
    def _env_with_installed(self, names: set[str]) -> MagicMock:
        env = MagicMock()
        env.conn.execute.return_value.fetchall.return_value = [
            (n,) for n in names
        ]
        return env

    def test_fresh_db_bootstraps_bundled_modules_only(self):
        env = self._env_with_installed(set())
        ordered = [_spec("base"), _spec("admin", ["base"]), _spec("partners", ["base"])]
        result = specs_to_install(env, ordered)
        self.assertEqual([s.name for s in result], ["base", "admin"])
        self.assertIn("base", BOOTSTRAP_MODULES)
        self.assertIn("admin", BOOTSTRAP_MODULES)
        self.assertNotIn("partners", BOOTSTRAP_MODULES)

    def test_bootstrap_modules_cover_pyvelm_modules_tree(self):
        self.assertGreaterEqual(len(BOOTSTRAP_MODULES), 2)
        for name in ("base", "admin", "reports", "vellum"):
            self.assertIn(name, BOOTSTRAP_MODULES)

    def test_existing_db_only_installed_modules(self):
        env = self._env_with_installed({"base", "admin", "partners"})
        ordered = [
            _spec("base"),
            _spec("admin", ["base"]),
            _spec("partners", ["base"]),
            _spec("crm", ["partners"]),
        ]
        result = specs_to_install(env, ordered)
        self.assertEqual([s.name for s in result], ["base", "admin", "partners"])

    def test_install_all_returns_everything(self):
        env = self._env_with_installed(set())
        ordered = [_spec("base"), _spec("reports", ["base"])]
        result = specs_to_install(env, ordered, install_all=True)
        self.assertEqual([s.name for s in result], ["base", "reports"])


class BootstrapAfterFullInstallTests(DatabaseTestCase):
    """Regression: _inherit must not mutate cached base Field descriptors."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_bootstrap_after_install_all(self):
        roots = BUILTIN_MODULE_ROOTS + [
            Path(__file__).resolve().parents[2] / "examples" / "modules"
        ]

        reg = Registry()
        env = Environment(self.conn, registry=reg, uid=1)
        loader.load_and_install(roots, env, install_all=True)

        reset_database(self.dsn)
        reg = Registry()
        env = Environment(self.conn, registry=reg, uid=1)
        loader.load_and_install(roots, env)
        install_module_action(env, list(roots), "partners")

        import base.models.country as base_country

        display = base_country.Country._fields["display_name"]
        self.assertNotIn("flag_emoji", display.depends_on)


if __name__ == "__main__":
    unittest.main()
