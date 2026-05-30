"""Raise coverage on loader, env, domain, storage, cli, reports, and workflow."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Float, Integer, Many2many, Many2one, One2many, Registry
from pyvelm.domain import (
    _parse_polish,
    domain_to_sql,
    expand_or_groups,
    is_domain_leaf,
    normalize_domain,
)
from pyvelm.env import Cache, Environment
from pyvelm.loader import (
    ModuleSpec,
    _import_attr,
    _iter_command_classes,
    _load_commands_from_package,
    _load_data_files,
    _menu_sync_order,
    _pad,
    _parse_migration_filename,
    _run_migrations,
    _sync_menus,
    _sync_view_inherits,
    _sync_views,
    discover,
    discover_commands,
    module_display_name,
    parse_module_roots_env,
    register_web_routes,
    resolve_order,
)
from pyvelm.reports.compile import ColumnMeta, CompiledReport
from pyvelm.reports.compile_collections import (
    _emit_m2o_joins,
    collection_subquery_sql,
    column_sql_for_path,
)
from pyvelm.reports.execute import (
    ReportResult,
    _resolve_currency_symbols,
    _resolve_m2o_labels,
    _secured_definition,
    run_report,
)
from pyvelm.reports.export_pdf import export_pdf
from pyvelm.reports.export_xlsx import export_xlsx
from pyvelm.reports.fields_api import list_active_currencies, list_exportable_fields
from pyvelm.reports.schema import ReportDefinitionError, validate_definition
from pyvelm.storage import (
    DbStorageBackend,
    LocalStorageBackend,
    _sanitize,
    get_backend,
    reset_backend_cache,
)
from pyvelm.workflow.engine import (
    WorkflowEngine,
    _approval_complete_message,
    _is_final_state,
    _maybe_advance_sequential,
    _resolve_assignees,
    _state_label,
    parse_definition,
)
from pyvelm.workflow.schema import WorkflowDefinitionError, validate_definition as wf_validate


# ---------------------------------------------------------------------------
# env.py
# ---------------------------------------------------------------------------


class CacheTests(unittest.TestCase):
    def test_invalidate_all_and_filtered(self):
        c = Cache()
        c.set("m", 1, "a", 1)
        c.set("m", 1, "b", 2)
        c.set("m", 2, "a", 3)
        c.invalidate(model_name="m", ids=[1], fields=["a"])
        self.assertFalse(c.contains("m", 1, "a"))
        self.assertTrue(c.contains("m", 1, "b"))
        c.invalidate()
        self.assertFalse(c.contains("m", 2, "a"))


class EnvironmentUnitTests(unittest.TestCase):
    def _minimal_registry(self):
        reg = Registry()
        with reg.activate():

            class Thing(BaseModel):
                _name = "test.thing"
                _table = "test_thing"
                name = Char()

        return reg

    def test_query_and_sudo_idempotent(self):
        reg = self._minimal_registry()
        conn = MagicMock()
        env = Environment(conn, reg, uid=2)
        qb = env.query("test.thing")
        self.assertEqual(qb.env, env)
        self.assertIs(env.sudo(False), env)
        env2 = env.sudo(True)
        self.assertTrue(env2._acl_bypass)
        env3 = env2.sudo(False)
        self.assertFalse(env3._acl_bypass)
        self.assertIs(env.sudo(False), env)

    def test_with_context_and_company(self):
        reg = self._minimal_registry()
        env = Environment(MagicMock(), reg)
        env2 = env.with_context(foo=1)
        self.assertEqual(env2.context["foo"], 1)
        env3 = env.with_company(5)
        self.assertEqual(env3.company_id, 5)
        env4 = env.with_company(None)
        self.assertIsNone(env4.company_id)

    def test_user_groups_cache_paths(self):
        reg = self._minimal_registry()
        env = Environment(MagicMock(), reg, uid=None)
        self.assertEqual(env.user_group_ids, set())

        reg2 = Registry()
        with reg2.activate():

            class Users(BaseModel):
                _name = "res.users"
                _table = "res_users"
                group_ids = Many2many("res.groups")

            class Groups(BaseModel):
                _name = "res.groups"
                _table = "res_groups"
                name = Char()

        UsersCls = reg2["res.users"]
        env2 = Environment(MagicMock(), reg2, uid=9)
        with patch.object(UsersCls, "search", return_value=UsersCls(env2, ())):
            self.assertEqual(env2.user_group_ids, set())

        user = MagicMock()
        user.group_ids.ids = [1, 2]
        env3 = Environment(MagicMock(), reg2, uid=9)
        with (
            patch.object(UsersCls, "browse", return_value=user),
            patch.object(UsersCls, "search", return_value=[user]),
        ):
            g1 = env3.user_group_ids
            g2 = env3.user_group_ids
        self.assertEqual(g1, {1, 2})
        self.assertIs(g2, g1)

    def test_prime_current_user_cache(self):
        reg = Registry()
        with reg.activate():

            class Users(BaseModel):
                _name = "res.users"
                _table = "res_users"
                name = Char()
                login = Char()
                company_id = Many2one("res.company")
                group_ids = Many2many("res.groups")

            class Company(BaseModel):
                _name = "res.company"
                _table = "res_company"
                name = Char()

            class Groups(BaseModel):
                _name = "res.groups"
                _table = "res_groups"
                name = Char()

        env = Environment(MagicMock(), reg, uid=1)
        UsersM = MagicMock()
        UsersM.search.return_value = []
        env.__getitem__ = lambda _s, n: UsersM if n == "res.users" else MagicMock()
        env.prime_current_user_cache()

        user = MagicMock()
        user.name = "A"
        user.login = "a"
        user.company_id = 1
        grp = MagicMock()
        grp.name = "Admin"
        user.group_ids = [grp]
        UsersM.search.return_value = [user]
        env.prime_current_user_cache()

    def test_access_and_policy_helpers(self):
        reg = Registry()
        with reg.activate():

            class Access(BaseModel):
                _name = "ir.model.access"
                _table = "ir_model_access"
                model = Char()
                perm_read = Char()
                group_id = Many2one("res.groups")

            class Rule(BaseModel):
                _name = "ir.rule"
                _table = "ir_rule"
                model = Char()
                perm_read = Char()
                domain = Char()
                group_id = Many2one("res.groups")

            class Partner(BaseModel):
                _name = "res.partner"
                _table = "res_partner"
                name = Char()

        env = Environment(MagicMock(), reg, uid=5)
        AccessCls = reg["ir.model.access"]
        RuleCls = reg["ir.rule"]
        env._user_groups_cache = {3}
        with patch.object(AccessCls, "search", return_value=[MagicMock()]):
            self.assertTrue(env.has_access("res.partner", "read"))
            env.check_access("res.partner", "read")
        with patch.object(AccessCls, "search", return_value=[]):
            env._access_cache.clear()
            with self.assertRaises(PermissionError):
                env.check_access("res.partner", "write")

        PartnerM = env["res.partner"]
        with patch("pyvelm.env.eval_policy", return_value=None):
            self.assertTrue(env.can(PartnerM, "archive"))
            env.check_can(PartnerM, "archive")
        with patch("pyvelm.env.eval_policy", return_value=False):
            with self.assertRaises(PermissionError):
                env.check_can(PartnerM, "archive", perm="read")

        rule = MagicMock()
        rule.domain = json.dumps([("create_uid", "=", {"placeholder": "uid"})])
        rule_rs = MagicMock()
        rule_rs.__iter__ = lambda s: iter([rule])
        with patch.object(RuleCls, "search", return_value=rule_rs):
            leaves = env.collect_record_rules("res.partner", "read")
        self.assertTrue(leaves)

        with self.assertRaises(ValueError):
            env._resolve_placeholder("unknown_ph")

    def test_transaction_commit_and_savepoint(self):
        conn = MagicMock()
        conn.autocommit = True
        reg = self._minimal_registry()
        env = Environment(conn, reg)
        with env.transaction():
            pass
        conn.commit.assert_called_once()
        conn.autocommit = True

        conn.reset_mock()
        conn.autocommit = False
        env._tx_depth = 1
        with env.transaction():
            pass
        self.assertTrue(any("SAVEPOINT" in str(c) for c in conn.execute.call_args_list))

    def test_transaction_rollback_on_error(self):
        conn = MagicMock()
        conn.autocommit = True
        conn.commit.side_effect = RuntimeError("aborted")
        env = Environment(conn, Registry())
        with self.assertRaises(RuntimeError):
            with env.transaction():
                pass
        conn.rollback.assert_called()

    def test_notify_changed_noop_and_cache_invalidate(self):
        reg = self._minimal_registry()
        env = Environment(MagicMock(), reg)
        env.notify_changed("test.thing", [], ["name"])
        env.cache.set("test.thing", 1, "name", "x")
        env.notify_changed("test.thing", [1], ["missing_field"])


# ---------------------------------------------------------------------------
# loader.py
# ---------------------------------------------------------------------------


class LoaderHelperTests(unittest.TestCase):
    def test_parse_module_roots_and_display_name(self):
        roots = parse_module_roots_env("/a,/b:./c")
        self.assertEqual(len(roots), 3)
        self.assertEqual(module_display_name("my_mod", "Custom"), "Custom")
        self.assertEqual(module_display_name("my_mod"), "My Mod")

    def test_pad_and_migration_filename(self):
        self.assertEqual(_pad((0, 1), 3), (0, 1, 0))
        self.assertIsNone(_parse_migration_filename("bad"))
        self.assertEqual(
            _parse_migration_filename("0_1_to_0_2"),
            ((0, 1), (0, 2)),
        )

    def test_discover_and_resolve_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skip.txt").write_text("x")
            (root / "mod_a").mkdir()
            (root / "mod_a" / "__pyvelm__.py").write_text(
                'NAME = "mod_a"\nVERSION = (0, 1, 0)\nDEPENDS = []\n',
                encoding="utf-8",
            )
            (root / "mod_b").mkdir()
            (root / "mod_b" / "__pyvelm__.py").write_text(
                'NAME = "mod_b"\nVERSION = (0, 1, 0)\nDEPENDS = ["mod_a"]\n',
                encoding="utf-8",
            )
            specs = discover([root])
            self.assertIn("mod_a", specs)
            ordered = resolve_order(specs)
            self.assertEqual([s.name for s in ordered], ["mod_a", "mod_b"])

            (root / "mod_c").mkdir()
            (root / "mod_c" / "__pyvelm__.py").write_text(
                'NAME = "mod_c"\nVERSION = (0, 1, 0)\nDEPENDS = ["mod_a", "mod_c"]\n',
                encoding="utf-8",
            )
            specs2 = discover([root])
            with self.assertRaises(ValueError):
                resolve_order(specs2)

    def test_load_data_files_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "pkg"
            pkg.mkdir()
            spec = ModuleSpec(
                name="pkg",
                version=(0, 1, 0),
                depends=[],
                package="pkg",
                models_package="pkg.models",
                migrations_package=None,
                package_path=pkg,
                data=["missing.py"],
            )
            with self.assertRaises(FileNotFoundError):
                _load_data_files(spec)
            (pkg / "bad.json").write_text("{}", encoding="utf-8")
            spec2 = ModuleSpec(
                name="pkg",
                version=(0, 1, 0),
                depends=[],
                package="pkg",
                models_package="pkg.models",
                migrations_package=None,
                package_path=pkg,
                data=["bad.json"],
            )
            with self.assertRaises(ValueError):
                _load_data_files(spec2)

    def test_menu_sync_order(self):
        menus = [
            {"name": "child", "label": "C", "parent": "pkg.parent"},
            {"name": "parent", "label": "P"},
            {"name": "ext", "label": "E", "parent": "other.root"},
        ]
        ordered = _menu_sync_order(menus, "pkg")
        names = [m["name"] for m in ordered]
        self.assertEqual(names[0], "parent")
        self.assertIn("child", names[1:])

    def test_sync_views_and_menus_mocked(self):
        reg = Registry()
        with reg.activate():

            class View(BaseModel):
                _name = "ir.ui.view"
                _table = "ir_ui_view"
                module = Char()
                name = Char()
                model = Char()
                view_type = Char()
                arch = Char()
                priority = Integer()
                inherit_id = Many2one("ir.ui.view")
                operations = Char()

            class Menu(BaseModel):
                _name = "ir.ui.menu"
                _table = "ir_ui_menu"
                module = Char()
                name = Char()
                label = Char()
                parent_id = Many2one("ir.ui.menu")
                sequence = Integer()
                href = Char()
                icon = Char()
                active = Char()
                access_model = Char()
                access_perm = Char()
                access_policy = Char()
                dev_only = Char()

        env = MagicMock()
        env.registry = reg
        ViewM = MagicMock()
        parent = MagicMock()
        parent.id = 5
        parent.model = "res.partner"
        parent.view_type = "list"
        parent_rs = MagicMock()
        parent_rs.__bool__ = lambda s: True
        parent_rs.ensure_one = MagicMock(return_value=parent)
        empty = MagicMock()
        empty.__bool__ = lambda s: False
        ViewM.search.side_effect = [
            empty,
            parent_rs,
            empty,
            empty,
            parent_rs,
            empty,
        ]
        MenuM = MagicMock()
        MenuM.search.side_effect = [[], []]
        env.__getitem__ = lambda _s, n: ViewM if n == "ir.ui.view" else MenuM

        spec = ModuleSpec(
            name="pkg",
            version=(0, 1, 0),
            depends=[],
            package="pkg",
            models_package="pkg.models",
            migrations_package=None,
            views=[
                {
                    "name": "p.list",
                    "model": "res.partner",
                    "view_type": "list",
                    "arch": {"fields": ["name"]},
                },
            ],
            view_inherits=[
                {
                    "name": "p.list.ext",
                    "inherit": "pkg.p.list",
                    "operations": [],
                },
            ],
            menus=[{"name": "m", "label": "Menu"}],
        )
        _sync_views(spec, env)
        ViewM.create.assert_called()
        _sync_view_inherits(spec, env)
        _sync_menus(spec, env)
        MenuM.create.assert_called()

    def test_sync_validation_errors(self):
        env = MagicMock()
        env.registry = {"ir.ui.view": object(), "ir.ui.menu": object()}
        spec = ModuleSpec(
            name="x",
            version=(0, 1, 0),
            depends=[],
            package="x",
            models_package="x.models",
            migrations_package=None,
            views=[{"name": "v"}],
        )
        with self.assertRaises(ValueError):
            _sync_views(spec, env)
        spec2 = ModuleSpec(
            name="x",
            version=(0, 1, 0),
            depends=[],
            package="x",
            models_package="x.models",
            migrations_package=None,
            view_inherits=[{"name": "e", "inherit": "bad", "operations": []}],
        )
        env.__getitem__ = MagicMock(return_value=MagicMock(search=MagicMock(return_value=[])))
        with self.assertRaises(ValueError):
            _sync_view_inherits(spec2, env)

    def test_run_migrations_and_register_web_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "m"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            mig = pkg / "migrations"
            mig.mkdir()
            (mig / "__init__.py").write_text("", encoding="utf-8")
            (mig / "0_1_to_0_2.py").write_text(
                "def migrate(env):\n    pass\n", encoding="utf-8",
            )
            spec = ModuleSpec(
                name="m",
                version=(0, 2, 0),
                depends=[],
                package="m",
                models_package="m.models",
                migrations_package="m.migrations",
                package_path=pkg,
            )
            root = str(tmp)
            if root not in sys.path:
                sys.path.insert(0, root)
            try:
                for key in list(sys.modules):
                    if key == "m" or key.startswith("m."):
                        del sys.modules[key]
                env = MagicMock()
                _run_migrations(spec, env, (0, 1, 0), (0, 2, 0))
                (mig / "bad_name.py").write_text("", encoding="utf-8")
                with self.assertRaises(ValueError):
                    _run_migrations(spec, env, (0, 1, 0), (0, 2, 0))
            finally:
                if root in sys.path:
                    sys.path.remove(root)

        app = MagicMock()
        with patch("pyvelm.loader.discover", return_value={}), patch(
            "pyvelm.loader.resolve_order", return_value=[],
        ):
            register_web_routes(app, [])

    def test_import_attr_and_discover_commands(self):
        from pyvelm.console import Command

        with tempfile.TemporaryDirectory() as tmp:
            cmd_py = Path(tmp) / "my_cmd.py"
            cmd_py.write_text(
                textwrap.dedent(
                    """
                    from pyvelm.console import Command

                    class HelloCommand(Command):
                        name = "hello:test"
                        description = "hi"

                        def handle(self, ctx, args):
                            return 0
                    """
                ),
                encoding="utf-8",
            )
            spec_obj = __import__("importlib.util", fromlist=["spec_from_file_location"]).spec_from_file_location(
                "_test_cmd", cmd_py
            )
            mod = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(spec_obj)
            spec_obj.loader.exec_module(mod)
            found = _iter_command_classes(mod)
            self.assertEqual(found[0].name, "hello:test")

            root = Path(tmp) / "roots"
            (root / "mod").mkdir(parents=True)
            (root / "mod" / "__pyvelm__.py").write_text(
                'NAME = "mod"\nVERSION = (0, 1, 0)\nDEPENDS = []\n'
                'COMMANDS = ["dummy:HelloCommand"]\n',
                encoding="utf-8",
            )
            with patch(
                "pyvelm.loader._import_attr",
                return_value=mod.HelloCommand,
            ):
                reg = discover_commands([root])
            self.assertIn("hello:test", reg.names())


# ---------------------------------------------------------------------------
# domain.py
# ---------------------------------------------------------------------------


def _rich_partner_registry():
    reg = Registry()
    with reg.activate():

        class Country(BaseModel):
            _name = "res.country"
            _table = "res_country"
            code = Char()

        class Tag(BaseModel):
            _name = "res.tag"
            _table = "res_tag"
            name = Char()
            country_id = Many2one("res.country")

        class Line(BaseModel):
            _name = "test.line"
            _table = "test_line"
            name = Char()
            partner_id = Many2one("test.partner")
            qty = Integer()

        class Partner(BaseModel):
            _name = "test.partner"
            _table = "test_partner"
            name = Char()
            line_ids = One2many("test.line", "partner_id")
            tag_ids = Many2many("res.tag")

    return reg, Partner


class DomainPolishTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _rich_partner_registry()

    def test_implicit_and_and_polish_not(self):
        norm = normalize_domain([("name", "=", "a"), ("name", "=", "b")])
        self.assertEqual(norm[0], "&")
        tree, _ = _parse_polish(["!", ("name", "=", "x")])
        self.assertEqual(tree[0], "!")
        where, _, _ = domain_to_sql(["!", ("name", "=", "x")], self.Partner, self.reg)
        self.assertIn("NOT", where)

    def test_exists_nested_hops_and_universal_like(self):
        where, params, _ = domain_to_sql(
            [("line_ids.partner_id.name", "=", "Acme")],
            self.Partner,
            self.reg,
        )
        self.assertIn("EXISTS", where)
        where2, _, _ = domain_to_sql(
            [("tag_ids.country_id.code", "=", "US")],
            self.Partner,
            self.reg,
        )
        self.assertIn("EXISTS", where2)
        where3, _, _ = domain_to_sql(
            [("line_ids.name", "like", "%x%", {"all": True})],
            self.Partner,
            self.reg,
        )
        self.assertIn("NOT LIKE", where3)

    def test_exists_empty_in_false_and_unknown_op(self):
        where, _, _ = domain_to_sql(
            [("tag_ids.name", "in", [])],
            self.Partner,
            self.reg,
        )
        self.assertEqual(where, "FALSE")
        with self.assertRaises(ValueError):
            domain_to_sql([("name", "??", "x")], self.Partner, self.reg)
        with self.assertRaises(ValueError):
            domain_to_sql(
                [("name", "=", "x", {"all": True})],
                self.Partner,
                self.reg,
            )

    def test_parse_polish_errors(self):
        with self.assertRaises(ValueError):
            _parse_polish([])
        with self.assertRaises(ValueError):
            normalize_domain([("name", "=", "a"), "&"])


# ---------------------------------------------------------------------------
# storage.py
# ---------------------------------------------------------------------------


class StorageMoreTests(unittest.TestCase):
    def tearDown(self):
        reset_backend_cache()

    def test_sanitize_and_invalid_key(self):
        self.assertEqual(_sanitize(""), "file")
        with tempfile.TemporaryDirectory() as tmp:
            b = LocalStorageBackend(root=tmp)
            with self.assertRaises(ValueError):
                b.load("../escape")
            key = b.save("test.txt", b"x")
            b.delete(key)
            b.delete(key)

    def test_unknown_backend(self):
        with patch.dict(os.environ, {"PYVELM_ATTACHMENT_BACKEND": "s3"}, clear=False):
            reset_backend_cache()
            with self.assertRaises(RuntimeError):
                get_backend()

    def test_db_backend_delete(self):
        DbStorageBackend().delete("")


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------


class CliCoverageMoreTests(unittest.TestCase):
    def test_default_module_roots_appends_find_modules_root(self):
        from pyvelm.cli import _default_module_roots

        app = Path(tempfile.mkdtemp())
        mod = app / "modules"
        mod.mkdir()
        try:
            with (
                patch("pyvelm.BUILTIN_MODULE_ROOTS", [Path("/builtin")]),
                patch("pyvelm.scaffolder.find_modules_root", return_value=mod),
                patch.dict(os.environ, {"PYVELM_MODULE_ROOTS": ""}, clear=False),
            ):
                roots = _default_module_roots()
            self.assertTrue(any(r.resolve() == mod.resolve() for r in roots))
        finally:
            import shutil

            shutil.rmtree(app, ignore_errors=True)

    def test_resolve_module_roots_with_explicit(self):
        from pyvelm.cli import _resolve_module_roots

        args = argparse.Namespace(roots=[Path("/extra")])
        with patch("pyvelm.BUILTIN_MODULE_ROOTS", [Path("/b")]):
            self.assertEqual(_resolve_module_roots(args), [Path("/b"), Path("/extra")])

    def test_build_db_env_missing_module(self):
        from pyvelm.cli import _build_db_env_and_spec

        args = argparse.Namespace(module="nope", roots=None)
        with (
            patch.dict(os.environ, {"PYVELM_DSN": "postgresql://localhost/db"}),
            patch("pyvelm.cli._resolve_module_roots", return_value=[]),
            patch("pyvelm.cli.loader.discover", return_value={}),
            self.assertRaises(SystemExit),
        ):
            _build_db_env_and_spec(args)

    def test_db_diff_null_warning_branch(self):
        from pyvelm.cli import _run_db_diff

        env, spec, conn = MagicMock(), MagicMock(), MagicMock()
        alt = MagicMock()
        alt.kind = "set_not_null"
        alt.table = "t"
        alt.column = "c"
        alt.cli_line.return_value = "line"
        diff = MagicMock(is_empty=False, new_tables=[], new_columns=[], alterations=[alt], orphan_columns=[])
        with (
            patch("pyvelm.cli._build_db_env_and_spec", return_value=(env, spec, conn)),
            patch("pyvelm.db_autogen.compute_diff", return_value=diff),
            patch("pyvelm.db_autogen.count_null_rows", return_value=3),
            patch("builtins.print"),
        ):
            _run_db_diff(argparse.Namespace(module="demo"))

    def test_db_autogen_writes_migration(self):
        from pyvelm.cli import _run_db_autogen

        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "demo"
            pkg.mkdir()
            (pkg / "__pyvelm__.py").write_text(
                "NAME = 'demo'\nVERSION = (0, 1, 0)\nDEPENDS = []\n",
                encoding="utf-8",
            )
            (pkg / "migrations").mkdir()
            spec = ModuleSpec(
                name="demo",
                version=(0, 1, 0),
                depends=[],
                package="demo",
                models_package="demo.models",
                migrations_package="demo.migrations",
                package_path=pkg,
            )
            env, conn = MagicMock(), MagicMock()
            diff = MagicMock(is_empty=False)
            with (
                patch("pyvelm.cli._build_db_env_and_spec", return_value=(env, spec, conn)),
                patch("pyvelm.db_autogen.compute_diff", return_value=diff),
                patch("pyvelm.db_autogen.render_migration", return_value="# m\n"),
                patch("pyvelm.db_autogen.next_minor_version", return_value=(0, 2, 0)),
                patch("pyvelm.db_autogen.migration_filename", return_value="0_1_to_0_2.py"),
                patch("builtins.print"),
            ):
                _run_db_autogen(
                    argparse.Namespace(
                        module="demo",
                        dry_run=False,
                        target_version=None,
                        with_views=False,
                    )
                )
            self.assertTrue((pkg / "migrations" / "0_1_to_0_2.py").is_file())

    def test_read_installed_versions_handles_missing_table(self):
        from pyvelm.cli import _read_installed_versions

        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("no table")
        self.assertEqual(_read_installed_versions(conn), {})

    def test_ordered_specs_missing_dependency(self):
        from pyvelm.cli import _ordered_specs_for_install

        spec = ModuleSpec(
            name="child",
            version=(0, 1, 0),
            depends=["missing"],
            package="child",
            models_package="child.models",
            migrations_package=None,
        )
        with (
            patch("pyvelm.cli.loader.discover", return_value={"child": spec}),
            self.assertRaises(SystemExit),
        ):
            _ordered_specs_for_install([], "child")

    def test_confirm_migrate_fresh_production_yes(self):
        from pyvelm.migrate_cli import confirm_migrate_fresh

        with patch("builtins.print"):
            confirm_migrate_fresh(production=True, yes=True)

    def test_confirm_nuke_eof(self):
        from pyvelm.cli import _confirm_nuke

        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(SystemExit):
                _confirm_nuke(dsn="postgresql://localhost/db", schema="public", yes=False)

    def test_run_command_help_unknown(self):
        from pyvelm.cli import _run_command_help

        with patch("pyvelm.cli._command_registry") as reg:
            reg.return_value.get.return_value = None
            with self.assertRaises(SystemExit):
                _run_command_help(argparse.Namespace(command_name="nope"))

    def test_try_dispatch_unknown_command(self):
        from pyvelm.cli import _try_dispatch_module_command

        with patch("pyvelm.cli._command_registry") as reg:
            reg.return_value.names.return_value = []
            self.assertFalse(_try_dispatch_module_command(["unknown:cmd"]))

    def test_main_no_command_prints_help(self):
        from pyvelm.cli import main

        with (
            patch("pyvelm.cli._load_dotenv"),
            patch("pyvelm.cli._try_dispatch_module_command", return_value=False),
            patch("pyvelm.cli._build_parser") as bp,
            patch("pyvelm.cli._command_registry") as reg,
        ):
            parser = MagicMock()
            parser.parse_args.return_value = argparse.Namespace(command=None)
            bp.return_value = parser
            reg.return_value.all.return_value = [
                SimpleNamespace(name="make:module", description="x"),
            ] * 10
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# reports/
# ---------------------------------------------------------------------------


def _partner_reg():
    reg = Registry()
    with reg.activate():

        class Country(BaseModel):
            _name = "res.country"
            _table = "res_country"
            name = Char()
            code = Char()

        class Currency(BaseModel):
            _name = "res.currency"
            _table = "res_currency"
            code = Char()
            symbol = Char()
            active = Char()

        class Partner(BaseModel):
            _name = "res.partner"
            _table = "res_partner"
            _company_scoped = True
            name = Char()
            amount = Float()
            country_id = Many2one("res.country")
            currency_id = Many2one("res.currency")
            child_ids = One2many("res.partner", inverse_name="parent_id")
            parent_id = Many2one("res.partner")
            tag_ids = Many2many("res.tag")

        class Tag(BaseModel):
            _name = "res.tag"
            _table = "res_tag"
            name = Char()
            country_id = Many2one("res.country")
            partner_ids = Many2many("res.partner")

    return reg


class ReportsExecuteMoreTests(unittest.TestCase):
    def test_secured_definition_adds_rules_and_company(self):
        reg = _partner_reg()
        env = MagicMock()
        env.registry = reg
        env.company_id = 7
        env._acl_bypass = False
        env.collect_record_rules.return_value = [("id", ">", 0)]
        defn = {"root": "res.partner", "filters": []}
        out = _secured_definition(defn, env)
        self.assertEqual(len(out["filters"]), 2)

    def test_run_report_with_row_key_order(self):
        reg = _partner_reg()
        env = MagicMock()
        env.registry = reg
        env.company_id = None
        env._acl_bypass = False
        env.collect_record_rules.return_value = []
        col = ColumnMeta(
            key="amount",
            label="Amount",
            expr="amount",
            format={"type": "currency", "currency_source": "field", "currency_field": "currency_id"},
            currency_id_key="amount__currency_id",
        )
        compiled = CompiledReport(
            sql="SELECT 1",
            params=[],
            columns=[col],
            row_key_order=[("data", "name"), ("ccy", "amount")],
            is_aggregate=False,
        )
        env.conn.execute.return_value.fetchall.return_value = [("Alice", 99)]
        with (
            patch("pyvelm.reports.execute.compile_report", return_value=compiled),
            patch("pyvelm.reports.fields_api.check_definition_access"),
            patch("pyvelm.reports.execute._resolve_m2o_labels"),
            patch("pyvelm.reports.execute._resolve_currency_symbols"),
        ):
            result = run_report(env, _detail_defn())
        self.assertEqual(result.rows[0]["name"], "Alice")
        self.assertEqual(result.rows[0]["amount__currency_id"], 99)

    def test_resolve_m2o_and_currency_helpers(self):
        reg = _partner_reg()
        env = Environment(MagicMock(), reg)
        rec = MagicMock()
        rec.id = 1
        rec.display_name = "Acme"
        rec._fields = {"display_name": object(), "name": object()}
        Country = reg["res.country"]
        rows = [{"country_id": 1}]
        cols = [ColumnMeta(key="country_id", label="C", expr="country_id", is_m2o=True, comodel="res.country")]
        with patch.object(Country, "browse", return_value=[rec]):
            _resolve_m2o_labels(env, cols, rows)
        self.assertEqual(rows[0]["country_id__label"], "Acme")

        cur = MagicMock()
        cur.id = 9
        cur.symbol = "$"
        cur.code = "USD"
        Currency = reg["res.currency"]
        rows2 = [{"amount": 1.0, "amount__currency_id": 9}]
        cols2 = [
            ColumnMeta(
                key="amount",
                label="A",
                expr="amount",
                format={"type": "currency", "currency_source": "field"},
                currency_id_key="amount__currency_id",
            ),
        ]
        with patch.object(Currency, "browse", return_value=[cur]):
            _resolve_currency_symbols(env, cols2, rows2)
        self.assertEqual(rows2[0]["amount__currency_symbol"], "$")

    def test_list_active_currencies(self):
        reg = _partner_reg()

        class Env:
            registry = reg

            def check_access(self, model, perm):
                return None

            def __getitem__(self, name):
                Cur = MagicMock()
                r = MagicMock()
                r.id = 1
                r.code = "USD"
                r.name = "Dollar"
                r.symbol = "$"
                Cur.search.return_value = [r]
                return Cur

        out = list_active_currencies(Env())
        self.assertEqual(out[0]["code"], "USD")


def _detail_defn():
    return {
        "version": 1,
        "root": "res.partner",
        "columns": [{"expr": "name", "label": "Name"}],
    }


class ReportsCollectionsMoreTests(unittest.TestCase):
    def test_m2m_subquery_and_emit_joins(self):
        reg = _partner_reg()
        from pyvelm.paths import parse_path

        path = parse_path(reg["res.partner"], "tag_ids.country_id.code", reg)
        sql = collection_subquery_sql(path, reg["res.partner"], '"res_partner"', reg, "sum")
        self.assertIn("SUM", sql)
        joins: list[str] = []
        aliases: dict = {}
        counter = [0]
        m2o_path = parse_path(reg["res.partner"], "country_id.code", reg)
        alias = _emit_m2o_joins(
            m2o_path.hops,
            '"res_partner"',
            reg,
            joins,
            aliases,
            counter,
        )
        self.assertTrue(alias.startswith("_j"))
        with self.assertRaises(ValueError):
            collection_subquery_sql(
                parse_path(reg["res.partner"], "name", reg),
                reg["res.partner"],
                '"res_partner"',
                reg,
                "count",
            )


class ReportsExportEdgeTests(unittest.TestCase):
    def test_pdf_xlsx_without_optional_deps(self):
        cols = [ColumnMeta(key="n", label="N", expr="n")]
        result = ReportResult(columns=cols, rows=[{"n": 1}], row_count=1, duration_ms=1)
        with patch.dict(sys.modules, {"fpdf": None}):
            with self.assertRaises(RuntimeError):
                export_pdf(result)
        with patch.dict(sys.modules, {"openpyxl": None}):
            with self.assertRaises(RuntimeError):
                export_xlsx(result)


# ---------------------------------------------------------------------------
# workflow/
# ---------------------------------------------------------------------------


_WF_SAMPLE = {
    "version": 1,
    "model": "wf.target",
    "states": [
        {"key": "draft", "label": "Draft", "initial": True},
        {"key": "done", "label": "Done", "final": True},
    ],
    "transitions": [
        {
            "key": "finish",
            "label": "Finish",
            "from": ["draft"],
            "to": "done",
            "kind": "user",
        },
    ],
}


class WorkflowEngineMoreTests(unittest.TestCase):
    def _registry(self):
        reg = Registry()
        with reg.activate():

            class Target(BaseModel):
                _name = "wf.target"
                _table = "wf_target"
                name = Char()
                owner_id = Many2one("res.users")

            class Users(BaseModel):
                _name = "res.users"
                _table = "res_users"
                group_ids = Many2many("res.groups")

            class Groups(BaseModel):
                _name = "res.groups"
                _table = "res_groups"
                name = Char()

        return reg

    def test_active_definition_and_instance_missing_registry(self):
        env = MagicMock()
        env.registry = {}
        self.assertIsNone(WorkflowEngine.active_definition(env, "x"))
        self.assertIsNone(WorkflowEngine.instance_for_record(env, "x", 1))

    def test_start_errors(self):
        reg = self._registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 2
        record = MagicMock(_name="wf.target", id=1)
        with self.assertRaises(WorkflowDefinitionError):
            WorkflowEngine.start(env, record, definition=None)

    def test_apply_transition_errors(self):
        reg = self._registry()
        env = MagicMock()
        env.registry = reg
        env.uid = 2
        definition = MagicMock(definition=json.dumps(_WF_SAMPLE))
        instance = MagicMock(
            state="done",
            pending_transition=False,
            definition_id=definition,
            res_model="wf.target",
            res_id=1,
            stage_data="{}",
        )
        instance.ensure_one = MagicMock()
        with self.assertRaises(WorkflowDefinitionError):
            WorkflowEngine.apply_transition(env, instance, "finish", {})

    def test_apply_transition_approval_kind(self):
        reg = self._registry()
        defn = {
            **_WF_SAMPLE,
            "transitions": [
                {
                    "key": "submit",
                    "label": "Submit",
                    "from": ["draft"],
                    "to": "done",
                    "kind": "approval",
                    "approval": {"strategy": "any", "assignee_type": "user", "user_id": 2},
                },
            ],
        }
        env = MagicMock()
        env.registry = reg
        env.uid = 2
        definition = MagicMock(definition=json.dumps(defn))
        instance = MagicMock(
            id=1,
            state="draft",
            pending_transition=False,
            definition_id=definition,
            res_model="wf.target",
            res_id=1,
            stage_data="{}",
        )
        instance.ensure_one = MagicMock()
        Target = MagicMock()
        Target.browse.return_value = MagicMock(write=MagicMock(), message_post=MagicMock())
        Approval = MagicMock()
        Task = MagicMock()

        def _getitem(_e, n):
            return {
                "wf.target": Target,
                "workflow.approval": Approval,
                "workflow.task": Task,
            }.get(n, MagicMock())

        env.__getitem__ = _getitem
        WorkflowEngine.apply_transition(env, instance, "submit", {})
        instance.write.assert_called()
        Approval.create.assert_called()

    def test_approve_completes_transition(self):
        reg = self._registry()
        defn = {
            **_WF_SAMPLE,
            "transitions": [
                {
                    "key": "submit",
                    "label": "Submit",
                    "from": ["draft"],
                    "to": "done",
                    "kind": "approval",
                    "approval": {"strategy": "any", "assignee_type": "user", "user_id": 2},
                },
            ],
        }
        env = MagicMock()
        env.registry = reg
        env.uid = 2
        definition = MagicMock(definition=json.dumps(defn))
        instance = MagicMock(
            id=1,
            state="draft",
            pending_transition="submit",
            definition_id=definition,
            res_model="wf.target",
            res_id=1,
            stage_data="{}",
        )
        approval = MagicMock(
            status="pending",
            transition_key="submit",
            instance_id=instance,
            assignee_user_id=MagicMock(id=2),
            assignee_group_id=None,
        )
        approval.ensure_one = MagicMock()
        instance.ensure_one = MagicMock()
        Approval = MagicMock()
        pending_rs = MagicMock()
        pending_rs.__iter__ = lambda s: iter([])
        pending_rs.__bool__ = lambda s: False
        approved = MagicMock(status="approved")
        done_rs = MagicMock()
        done_rs.__iter__ = lambda s: iter([approved])
        done_rs.__bool__ = lambda s: True
        Approval.search.side_effect = [pending_rs, done_rs]
        Target = MagicMock()
        Target.browse.return_value = MagicMock(message_post=MagicMock())
        env.__getitem__ = lambda _e, n: {
            "workflow.approval": Approval,
            "wf.target": Target,
        }[n]
        WorkflowEngine.approve(env, approval, approved=True)
        instance.write.assert_called()

    def test_resolve_assignees_group_all(self):
        reg = self._registry()
        env = MagicMock()
        env.registry = reg
        tr = {
            "approval": {
                "assignee_type": "group",
                "strategy": "all",
                "group_id": 3,
            },
        }
        User = MagicMock()
        User.search.return_value = [MagicMock(id=4), MagicMock(id=5)]
        Group = MagicMock()
        env.__getitem__ = lambda _e, n: User if n == "res.users" else Group
        specs = _resolve_assignees(env, MagicMock(res_model="wf.target", res_id=1), tr, 1)
        self.assertEqual(len(specs), 2)

    def test_sequential_advance_and_labels(self):
        reg = self._registry()
        env = MagicMock()
        tr = {"key": "a", "approval": {"strategy": "sequential", "deadline_hours": 48}}
        instance = MagicMock(
            id=1,
            stage_data=json.dumps({"_wf_queue": [{"user_id": 9}]}),
        )
        Approval = MagicMock()
        Approval.search.return_value = []
        env.__getitem__ = lambda _e, n: Approval
        env.uid = 1
        _maybe_advance_sequential(env, instance, tr)
        instance.write.assert_called()
        self.assertEqual(_state_label(_WF_SAMPLE, "draft"), "Draft")
        self.assertTrue(_is_final_state(_WF_SAMPLE, "done"))
        msg = _approval_complete_message(_WF_SAMPLE, _WF_SAMPLE["transitions"][0])
        self.assertIn("Done", msg)


class WorkflowSchemaMoreTests(unittest.TestCase):
    def test_schema_rejects_bad_auto_start(self):
        reg = Registry()
        with reg.activate():

            class Target(BaseModel):
                _name = "wf.target"
                name = Char()

        bad = {
            "version": 1,
            "model": "wf.target",
            "auto_start": "yes",
            "states": _WF_SAMPLE["states"],
            "transitions": [],
        }
        with self.assertRaises(WorkflowDefinitionError):
            wf_validate(bad, reg)


class DomainExtraCoverageTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _rich_partner_registry()

    def test_invalid_leaf_opts_type(self):
        with self.assertRaises(ValueError):
            domain_to_sql([("name", "=", "x", "bad")], self.Partner, self.reg)

    def test_exists_universal_not_in_empty(self):
        where, _, _ = domain_to_sql(
            [("tag_ids.name", "not in", [], {"all": True})],
            self.Partner,
            self.reg,
        )
        self.assertEqual(where, "TRUE")

    def test_exists_universal_like(self):
        where, _, _ = domain_to_sql(
            [("line_ids.name", "like", "%a%", {"all": True})],
            self.Partner,
            self.reg,
        )
        self.assertIn("NOT LIKE", where)

    def test_domain_trailing_polish_tokens(self):
        with self.assertRaises(ValueError):
            domain_to_sql(["&", ("name", "=", "a")], self.Partner, self.reg)


class ReportSchemaCoverageTests(unittest.TestCase):
    def setUp(self):
        self.reg = _partner_reg()

    def _base(self, **extra):
        d = {"version": 1, "root": "res.partner", "columns": [{"expr": "name", "label": "Name"}]}
        d.update(extra)
        return d

    def test_filters_must_be_list(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(filters="x"), self.reg)

    def test_parameters_must_be_list(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(parameters={"x": 1}), self.reg)

    def test_groupby_entries_strings(self):
        with self.assertRaises(ReportDefinitionError):
            validate_definition(self._base(groupby=[1]), self.reg)

    def test_duplicate_parameter_name(self):
        defn = self._base(
            parameters=[{"name": "q", "type": "string"}, {"name": "q", "type": "string"}],
        )
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, self.reg)

    def test_currency_format_validation(self):
        defn = {
            "version": 1,
            "root": "res.partner",
            "columns": [{
                "expr": "amount",
                "label": "A",
                "format": {"type": "currency", "currency_source": "fixed", "currency_id": "x"},
            }],
        }
        with self.assertRaises(ReportDefinitionError):
            validate_definition(defn, self.reg)


class LoaderInstallTests(unittest.TestCase):
    def test_install_fresh_module(self):
        from pyvelm.loader import install

        reg = Registry()
        with reg.activate():

            class Thing(BaseModel):
                _name = "tmp.thing"
                _table = "tmp_thing"
                name = Char()

        spec = ModuleSpec(
            name="tmp",
            version=(0, 1, 0),
            depends=[],
            package="tmp",
            models_package="tmp.models",
            migrations_package=None,
        )
        conn = MagicMock()
        env = Environment(conn, reg)
        applied = MagicMock()
        applied.summary.return_value = "schema ok"

        tx = MagicMock()
        tx.__enter__ = MagicMock(return_value=env)
        tx.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(env, "transaction", return_value=tx),
            patch("pyvelm.loader._ensure_ir_module"),
            patch("pyvelm.loader._installed_version", return_value=None),
            patch("pyvelm.loader._setup_module_schema"),
            patch("pyvelm.loader._load_data_files"),
            patch("pyvelm.loader._sync_views"),
            patch("pyvelm.loader._sync_view_inherits"),
            patch("pyvelm.loader._sync_menus"),
            patch("pyvelm.db_autogen.apply_schema_diff", return_value=applied),
        ):
            results = install([spec], env)
        self.assertEqual(results[0]["name"], "tmp")
        conn.execute.assert_called()


if __name__ == "__main__":
    unittest.main()
