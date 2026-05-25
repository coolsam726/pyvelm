"""CLI tests for ``pyvelm db migrate`` and ``pyvelm db status``."""

from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import MagicMock, patch

from pyvelm.cli import _run_db_migrate, _run_db_status
from pyvelm.loader import ModuleSpec


class DbMigrateCliTests(unittest.TestCase):
    def test_migrate_loads_models_and_installs(self):
        spec = ModuleSpec(
            name="demo",
            version=(0, 1, 0),
            depends=[],
            package="demo",
            models_package="demo.models",
            migrations_package="demo.migrations",
            package_path=None,
            data=[],
        )
        ordered = [spec]
        install_results = [
            {
                "name": "demo",
                "schema": "schema: 1 column(s)",
                "views": "2 view(s)",
                "menus": "1 menu(s)",
            }
        ]

        conn = MagicMock()
        conn_cm = MagicMock()
        conn_cm.__enter__ = MagicMock(return_value=conn)
        conn_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("pyvelm.cli.os.environ.get", return_value="postgresql://test"),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli.loader.discover", return_value={"demo": spec}),
            patch("pyvelm.cli.loader.resolve_order", return_value=ordered),
            patch("pyvelm.cli.loader._load_models") as load_models,
            patch("pyvelm.cli.loader.install", return_value=install_results) as install,
            patch("pyvelm.cli.psycopg.connect", return_value=conn_cm),
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

