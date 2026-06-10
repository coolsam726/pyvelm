"""Tests for Laravel-style :mod:`pyvelm.seeding`."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.seeding import (
    Seeder,
    bulk_insert_stored,
    discover_seeders,
    fetch_column_map,
    fetch_int_column_set,
    normalize_seeder_ref,
    resolve_module_seeders,
    resolve_seeder,
    run_seeders,
)


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


class SeederHelperTests(unittest.TestCase):
    def test_disabled_seeder_logs_and_returns_none(self):
        class _Off(Seeder):
            enabled = False

            def run_instance(self, env, **context):
                raise AssertionError("disabled")

        self.assertIsNone(_Off.run(MagicMock()))

    def test_normalize_seeder_ref_variants(self):
        self.assertEqual(
            normalize_seeder_ref("DemoSeeder", package="pkg"),
            "pkg.seeders:DemoSeeder",
        )
        self.assertEqual(
            normalize_seeder_ref("pkg.seeders:DemoSeeder", package="pkg"),
            "pkg.seeders:DemoSeeder",
        )
        self.assertEqual(
            normalize_seeder_ref(_AlphaSeeder, package="pkg"),
            f"{__name__}:_AlphaSeeder",
        )
        with self.assertRaises(ValueError):
            normalize_seeder_ref("  ", package="pkg")
        with self.assertRaises(TypeError):
            normalize_seeder_ref(42, package="pkg")

    def test_discover_seeders_empty_paths(self):
        self.assertEqual(discover_seeders("pkg", None), [])
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "nopkg"
            pkg.mkdir()
            self.assertEqual(discover_seeders("nopkg", pkg), [])

    def test_resolve_module_seeders_manifest_wins(self):
        refs = resolve_module_seeders("pkg", None, ["CustomSeeder"])
        self.assertEqual(refs, ["pkg.seeders:CustomSeeder"])

    def test_resolve_seeder_dot_path_and_invalid(self):
        dotted = f"{__name__}._AlphaSeeder"
        self.assertIs(resolve_seeder(dotted), _AlphaSeeder)
        with self.assertRaises(TypeError):
            resolve_seeder(f"{__name__}:SeederTests")

    def test_fetch_column_map_and_int_set(self):
        from pyvelm import BaseModel, Char, Integer, Registry
        from pyvelm.env import Environment
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "res.country"
                _table = "res_country"
                code = Char.bare()
                geoname_id = Integer()

        executed: list[str] = []
        conn = MagicMock()
        wire_sa_conn(
            conn,
            executed,
            dialect_name="postgresql",
            base_execute=lambda sql, params=None: _rows_result(
                [("US", 1), ("CA", 2)]
            ),
        )
        env = Environment(conn, registry=reg, uid=1)

        mapping = fetch_column_map(env, "res_country", "code", model_cls=Country)
        self.assertEqual(mapping, {"US": 1, "CA": 2})

        wire_sa_conn(
            conn,
            executed,
            dialect_name="postgresql",
            base_execute=lambda sql, params=None: _rows_result([(10,), (20,)]),
        )
        ids = fetch_int_column_set(env, "res_country", "geoname_id", model_cls=Country)
        self.assertEqual(ids, {10, 20})

    def test_field_row_to_sql_skips_computed_and_adds_timestamps(self):
        from pyvelm import BaseModel, Char, Registry
        from pyvelm.seeding import _field_row_to_sql

        reg = Registry()
        with reg.activate():

            class Row(BaseModel):
                _name = "demo.row"
                _table = "demo_row"
                name = Char(required=True)

            ghost = Char.bare()
            ghost.name = "ghost"
            ghost.column = "ghost"
            ghost.is_stored = True
            ghost.compute = "_ghost"
            Row._fields["ghost"] = ghost

        sql = _field_row_to_sql(Row, {"name": "A", "ghost": 1})
        self.assertIn("name", sql)
        self.assertNotIn("ghost", sql)

    def test_fetch_int_column_set_uses_registry(self):
        from pyvelm import BaseModel, Integer, Registry
        from pyvelm.env import Environment
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        reg = Registry()
        with reg.activate():

            class Thing(BaseModel):
                _name = "demo.thing"
                _table = "demo_thing"
                geoname_id = Integer()

        conn = MagicMock()
        wire_sa_conn(
            conn,
            [],
            dialect_name="postgresql",
            base_execute=lambda sql, params=None: _rows_result([(99,)]),
        )
        env = Environment(conn, registry=reg, uid=1)
        self.assertEqual(
            fetch_int_column_set(env, "demo_thing", "geoname_id", registry=reg),
            {99},
        )

    def test_bulk_insert_stored_batches(self):
        from pyvelm import BaseModel, Char, Registry
        from pyvelm.env import Environment
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        reg = Registry()
        with reg.activate():

            class Tag(BaseModel):
                _name = "res.tag"
                _table = "res_tag"
                name = Char(required=True)

        conn = MagicMock()
        wire_sa_conn(conn, [], dialect_name="postgresql")
        env = Environment(conn, registry=reg, uid=1)
        rows = [{"name": f"T{i}"} for i in range(3)]
        count = bulk_insert_stored(env, Tag, rows, chunk_size=2)
        self.assertEqual(count, 3)
        self.assertEqual(bulk_insert_stored(env, Tag, []), 0)

    def test_run_instance_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            Seeder().run_instance(MagicMock())

    def test_discover_seeders_empty_when_no_entry_class(self):
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "empty_pkg"
            seeders = pkg / "seeders"
            seeders.mkdir(parents=True)
            (seeders / "__init__.py").write_text("# no DatabaseSeeder\n", encoding="utf-8")
            tmp_str = str(tmp)
            if tmp_str not in sys.path:
                sys.path.insert(0, tmp_str)
            self.assertEqual(discover_seeders("empty_pkg", pkg), [])

    def test_fetch_column_map_skips_null_keys_and_no_normalize(self):
        from pyvelm import BaseModel, Char, Registry
        from pyvelm.env import Environment
        from pyvelm.tests.support.sa_ddl import wire_sa_conn

        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "res.country"
                _table = "res_country"
                code = Char.bare()

        conn = MagicMock()
        wire_sa_conn(
            conn,
            [],
            dialect_name="postgresql",
            base_execute=lambda sql, params=None: _rows_result([(None, 1), ("fr", 2)]),
        )
        env = Environment(conn, registry=reg, uid=1)
        mapping = fetch_column_map(
            env,
            "res_country",
            "code",
            registry=reg,
            normalize_key=None,
        )
        self.assertEqual(mapping, {"fr": 2})


def _rows_result(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    result.fetchone.return_value = rows[0] if rows else None
    return result


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
