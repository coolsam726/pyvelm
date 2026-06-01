"""Tests for Laravel-style :mod:`pyvelm.seeding`."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.seeding import Seeder, run_seeders


class _AlphaSeeder(Seeder):
    order: list[str] = []

    def run_instance(self, env, **context):
        self.order.append("alpha")
        return "alpha"


class _BetaSeeder(Seeder):
    order: list[str] = []

    def run_instance(self, env, **context):
        self.order.append("beta")
        return context.get("from_alpha")


class _OrchestratorSeeder(Seeder):
    def run_instance(self, env, **context):
        out = self.call(env, _AlphaSeeder)
        self.call(env, _BetaSeeder, from_alpha=out)
        return out


class SeederTests(unittest.TestCase):
    def setUp(self):
        _AlphaSeeder.order.clear()
        _BetaSeeder.order.clear()

    def test_call_runs_seeders_in_order(self):
        env = MagicMock()
        _OrchestratorSeeder.run(env)
        self.assertEqual(_AlphaSeeder.order, ["alpha"])
        self.assertEqual(_BetaSeeder.order, ["beta"])

    def test_should_run_false_skips(self):
        class _SkipSeeder(Seeder):
            @classmethod
            def should_run(cls, env, **context):
                return False

            def run_instance(self, env, **context):
                raise AssertionError("should not run")

        self.assertIsNone(_SkipSeeder.run(MagicMock()))

    def test_run_seeders_resolves_dotted_path(self):
        env = MagicMock()
        dotted = f"{__name__}:_AlphaSeeder"
        results = run_seeders(env, [dotted], module="test")
        self.assertEqual(results, ["alpha"])


class LoaderInstallSeederTests(unittest.TestCase):
    def _install_with_patches(self, *, installed_version):
        from contextlib import ExitStack

        from pyvelm.loader import ModuleSpec, install

        spec = ModuleSpec(
            name="demo",
            version=(1, 0, 0),
            depends=[],
            package="demo",
            models_package="demo.models",
            migrations_package=None,
            seeders=[f"{__name__}:_AlphaSeeder"],
        )
        env = MagicMock()
        applied = MagicMock()
        applied.summary.return_value = ""
        with ExitStack() as stack:
            stack.enter_context(patch("pyvelm.loader._ensure_ir_module"))
            stack.enter_context(
                patch(
                    "pyvelm.loader._installed_version",
                    return_value=installed_version,
                )
            )
            stack.enter_context(patch("pyvelm.loader._setup_module_schema"))
            stack.enter_context(
                patch(
                    "pyvelm.db_autogen.apply_schema_diff",
                    return_value=applied,
                )
            )
            stack.enter_context(patch("pyvelm.loader._load_data_files"))
            stack.enter_context(patch("pyvelm.loader._sync_views"))
            stack.enter_context(patch("pyvelm.loader._sync_view_inherits"))
            stack.enter_context(patch("pyvelm.loader._sync_menus"))
            stack.enter_context(
                patch("pyvelm.database._conn_capabilities", return_value=MagicMock())
            )
            if installed_version is not None:
                stack.enter_context(patch("pyvelm.loader._run_migrations"))
            run_seeders = stack.enter_context(
                patch("pyvelm.loader._run_module_seeders")
            )
            install([spec], env)
        return run_seeders

    def test_install_runs_seeders_on_first_install(self):
        run_seeders = self._install_with_patches(installed_version=None)
        run_seeders.assert_called_once()

    def test_install_runs_seeders_on_upgrade_and_sync(self):
        run_seeders = self._install_with_patches(installed_version=(0, 1, 0))
        run_seeders.assert_called_once()


class DiscoverSeedersTests(unittest.TestCase):
    def test_discovers_seeders_list_from_package_init(self):
        import sys
        import tempfile
        from pathlib import Path

        from pyvelm import BUILTIN_MODULE_ROOTS
        from pyvelm.seeding import Seeder, discover_seeders

        root = BUILTIN_MODULE_ROOTS[0]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        discovered = discover_seeders("geo_data", Path(root) / "geo_data")
        self.assertEqual(
            discovered,
            ["geo_data.seeders.geography:GeographyDatabaseSeeder"],
        )

    def test_database_seeder_convention_when_seeders_list_omitted(self):
        import textwrap
        import sys
        import tempfile
        from pathlib import Path

        from pyvelm.seeding import Seeder, discover_seeders

        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "demo_pkg"
            seeders = pkg / "seeders"
            seeders.mkdir(parents=True)
            (seeders / "__init__.py").write_text(
                "from .database import DatabaseSeeder\n",
                encoding="utf-8",
            )
            (seeders / "database.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.seeding import Seeder

                    class DatabaseSeeder(Seeder):
                        def run_instance(self, env, **context):
                            return None
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            tmp_str = str(tmp)
            if tmp_str not in sys.path:
                sys.path.insert(0, tmp_str)
            discovered = discover_seeders("demo_pkg", pkg)
        self.assertEqual(discovered, ["demo_pkg.seeders:DatabaseSeeder"])


class LoaderSeederIntegrationTests(unittest.TestCase):
    def test_run_module_seeders_invokes_manifest_list(self):
        from pyvelm.loader import ModuleSpec, _run_module_seeders

        env = MagicMock()
        spec = ModuleSpec(
            name="geo_data",
            version=(0, 2, 0),
            depends=["base"],
            package="geo_data",
            models_package="geo_data.models",
            migrations_package="geo_data.migrations",
            seeders=[f"{__name__}:_AlphaSeeder"],
        )
        with patch("pyvelm.seeding.run_seeders") as run:
            _run_module_seeders(spec, env)
        run.assert_called_once_with(env, spec.seeders, module="geo_data")
