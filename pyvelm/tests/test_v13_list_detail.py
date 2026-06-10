"""v1.3.0 — list bulk actions, DetailView, IDE field-builder stubs."""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pyvelm import BaseModel, BUILTIN_MODULE_ROOTS, Boolean, Char, Integer, Environment, Registry
from pyvelm.builders import DetailView, FormView, ListView, Notebook, Page
from pyvelm.render import (
    _build_list_rows,
    _find_detail_view,
    _list_record_href,
    _resolve_bulk_actions,
    render_form_page,
    render_list_page,
    render_list_rows,
)
from pyvelm.stub_generators import _render_fields_stubs, load_stub_index
from pyvelm.tests._isolation import purge_import_prefix
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database
from pyvelm.views import normalize_arch
from pyvelm.web import create_app


def make_access(*, read=True, write=True):
    return SimpleNamespace(can_read=read, can_write=write)


class ResolveBulkActionsTests(unittest.TestCase):
    def test_default_unlink_when_permitted(self):
        env = MagicMock()
        env.has_access.return_value = True
        acts = _resolve_bulk_actions({}, env, model="demo.item")
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["action"], "unlink")
        self.assertIn("confirm", acts[0])

    def test_no_default_without_unlink(self):
        env = MagicMock()
        env.has_access.return_value = False
        self.assertEqual(_resolve_bulk_actions({}, env, model="demo.item"), [])

    def test_declared_actions_filter_by_perm(self):
        env = MagicMock()
        env.has_access.side_effect = lambda _m, perm: perm == "write"
        arch = {
            "bulk_actions": [
                {"action": "unlink", "label": "Delete", "perm": "unlink"},
                {"action": "archive", "label": "Archive", "perm": "write"},
            ]
        }
        acts = _resolve_bulk_actions(arch, env, model="demo.item")
        self.assertEqual([a["action"] for a in acts], ["archive"])

    def test_declared_actions_skip_missing_perm(self):
        env = MagicMock()
        env.has_access.return_value = False
        arch = {
            "bulk_actions": [
                {"action": "unlink", "label": "Delete", "perm": "unlink"},
            ]
        }
        self.assertEqual(_resolve_bulk_actions(arch, env, model="demo.item"), [])

    def test_declared_action_defaults(self):
        env = MagicMock()
        env.has_access.return_value = True
        acts = _resolve_bulk_actions(
            {"bulk_actions": [{"action": "unlink"}]},
            env,
            model="demo.item",
        )
        self.assertEqual(acts[0]["label"], "Run")
        self.assertEqual(acts[0]["confirm"], "")


class FindDetailViewTests(unittest.TestCase):
    def test_no_ir_ui_view_registry(self):
        view = SimpleNamespace(model="demo.item", module="demo")
        env = SimpleNamespace(registry={})
        self.assertIsNone(_find_detail_view(view, env))

    @patch("pyvelm.render._search_ui_views")
    def test_returns_first_detail_view_name(self, search):
        view = SimpleNamespace(model="demo.item", module="demo")
        env = SimpleNamespace(registry={"ir.ui.view": object()})
        search.return_value = [SimpleNamespace(name="item.detail")]
        self.assertEqual(_find_detail_view(view, env), "item.detail")

    @patch("pyvelm.render._search_ui_views")
    def test_returns_none_when_missing(self, search):
        view = SimpleNamespace(model="demo.item", module="demo")
        env = SimpleNamespace(registry={"ir.ui.view": object()})
        search.return_value = []
        self.assertIsNone(_find_detail_view(view, env))


class ListRecordHrefTests(unittest.TestCase):
    view = SimpleNamespace(module="demo", name="item.list")

    def test_custom_record_href_when_writable(self):
        href = _list_record_href(
            self.view,
            7,
            detail_view_name=None,
            form_view_name="item.form",
            record_href="/custom/{id}",
            list_nav_query="bc=1",
            access=make_access(write=True),
        )
        self.assertEqual(href, "/custom/7")

    def test_detail_view_when_readable(self):
        href = _list_record_href(
            self.view,
            7,
            detail_view_name="item.detail",
            form_view_name="item.form",
            record_href=None,
            list_nav_query="bc=1",
            access=make_access(read=True, write=False),
        )
        self.assertEqual(href, "/web/views/demo/item.detail/record/7?bc=1")

    def test_form_view_when_readable(self):
        href = _list_record_href(
            self.view,
            7,
            detail_view_name=None,
            form_view_name="item.form",
            record_href=None,
            list_nav_query="",
            access=make_access(read=True, write=False),
        )
        self.assertEqual(href, "/web/views/demo/item.form/record/7")

    def test_none_when_no_targets(self):
        href = _list_record_href(
            self.view,
            7,
            detail_view_name=None,
            form_view_name=None,
            record_href=None,
            list_nav_query="",
            access=make_access(read=False, write=False),
        )
        self.assertIsNone(href)


class BuildListRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = Registry()
        with cls.reg.activate():

            class Item(BaseModel):
                _name = "test.v13.item"
                name = Char()

        cls.reg = cls.reg

    def setUp(self):
        self.env = MagicMock()
        self.env.registry = self.reg
        self.Model = MagicMock()
        rec = SimpleNamespace(id=1, name="Alpha")
        self.Model.browse.return_value = rec
        self.env.__getitem__.return_value = self.Model
        self.view = SimpleNamespace(module="t", name="item.list", model="test.v13.item")
        self.arch = {"fields": ["name"]}
        row = SimpleNamespace(id=1)
        self.recordset = [row]

    @patch("pyvelm.render._build_rows")
    def test_passthrough_without_row_actions(self, build_rows):
        build_rows.return_value = [{"id": 1, "cells": []}]
        rows = _build_list_rows(
            self.view, self.recordset, self.arch["fields"], self.env, self.arch
        )
        self.assertEqual(rows, [{"id": 1, "cells": []}])
        build_rows.assert_called_once()

    @patch("pyvelm.render._resolve_header_actions")
    @patch("pyvelm.render._build_rows")
    def test_resolves_row_actions(self, build_rows, resolve):
        build_rows.return_value = [{"id": 1, "cells": []}]
        resolve.return_value = [{"label": "Go", "url": "/x"}]
        arch = {
            **self.arch,
            "row_actions": [{"label": "Go", "method": "GET", "url": "/x/{id}"}],
        }
        rows = _build_list_rows(
            self.view, self.recordset, arch["fields"], self.env, arch
        )
        self.assertEqual(rows[0]["row_actions"], [{"label": "Go", "url": "/x"}])
        resolve.assert_called_once()


class ListDetailBuilderTests(unittest.TestCase):
    def test_list_detail_bulk_row_actions(self):
        d = (
            ListView.make("item.list")
            .model("demo.item")
            .columns(["name"])
            .domain([("active", "=", True)])
            .detail_view("item.detail")
            .bulk_actions([{"action": "unlink", "label": "Remove"}])
            .row_actions([{"label": "Open", "method": "GET", "url": "/x"}])
            .to_dict()
        )
        self.assertEqual(d["arch"]["detail_view"], "item.detail")
        self.assertEqual(d["arch"]["domain"], [("active", "=", True)])
        self.assertEqual(d["arch"]["bulk_actions"][0]["action"], "unlink")
        self.assertEqual(d["arch"]["row_actions"][0]["label"], "Open")

    def test_list_view_missing_model_raises(self):
        with self.assertRaises(ValueError):
            ListView.make("item.list").to_dict()

    def test_detail_view_builder_full(self):
        d = (
            DetailView.make("item.detail")
            .model("demo.item")
            .title("Item")
            .cols(2)
            .form_view("item.form")
            .header_actions([{"label": "Print", "method": "GET", "url": "/print"}])
            .priority(8)
            .section("main", "Main", ["name"], cols=1)
            .notebook(
                "tabs",
                "Tabs",
                [Page.make("extra", "Extra").fields(["code"])],
                cols=2,
            )
            .sections([{"name": "flat", "fields": ["name"]}])
            .to_dict()
        )
        self.assertEqual(d["view_type"], "detail")
        self.assertEqual(d["priority"], 8)
        self.assertEqual(d["arch"]["title"], "Item")
        self.assertEqual(d["arch"]["cols"], 2)
        self.assertEqual(d["arch"]["form_view"], "item.form")
        self.assertEqual(d["arch"]["header_actions"][0]["label"], "Print")
        self.assertEqual(len(d["arch"]["sections"]), 1)

    def test_detail_view_notebook_dict_pages(self):
        d = (
            DetailView.make("item.detail")
            .model("demo.item")
            .notebook(
                "tabs",
                "Tabs",
                [{"name": "extra", "title": "Extra", "fields": ["name"]}],
            )
            .to_dict()
        )
        self.assertEqual(d["arch"]["sections"][0]["name"], "tabs")

    def test_detail_view_missing_model_raises(self):
        with self.assertRaises(ValueError):
            DetailView.make("item.detail").to_dict()

    def test_normalize_detail_arch(self):
        arch = normalize_arch(
            {"sections": [{"name": "s", "fields": ["a", "b"]}]},
            "detail",
        )
        self.assertEqual(arch["sections"][0]["fields"][0], {"name": "a"})


class FieldBuilderStubTests(unittest.TestCase):
    def test_stubs_include_orm_field_builder(self):
        text = _render_fields_stubs()
        self.assertIn("OrmFieldBuilder", text)
        self.assertIn("def __new__(cls) -> OrmFieldBuilder", text)
        self.assertIn("class Char(_Char):", text)

    def test_load_stub_index_skips_view_without_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "erp"
            root.mkdir()
            (root / "pyvelm.toml").write_text(
                'modules_root = "app/modules"\n', encoding="utf-8"
            )
            mod = root / "app" / "modules" / "demo"
            mod.mkdir(parents=True)
            (mod / "__init__.py").write_text("", encoding="utf-8")
            (mod / "models").mkdir(parents=True)
            (mod / "views").mkdir(parents=True)
            (mod / "__pyvelm__.py").write_text(
                textwrap.dedent(
                    """
                    NAME = "demo"
                    VERSION = (0, 1, 0)
                    DEPENDS: list[str] = []
                    DATA: list[str] = ["views/item.py"]
                    """
                ),
                encoding="utf-8",
            )
            (mod / "models" / "__init__.py").write_text("", encoding="utf-8")
            (mod / "views" / "item.py").write_text(
                textwrap.dedent(
                    """
                    VIEWS = [{"model": "demo.item", "view_type": "list", "arch": {}}]
                    """
                ),
                encoding="utf-8",
            )
            _reg, _specs, index = load_stub_index(
                modules_root=root / "app" / "modules"
            )
            self.assertNotIn("demo.", index.qualified_views)


def _write_v13_module(root: Path) -> list[Path]:
    """Materialize a throwaway module with list, detail, and form views."""
    mods = root / "modules" / "v13test"
    mods.mkdir(parents=True)
    (mods / "__init__.py").write_text("", encoding="utf-8")
    (mods / "models").mkdir(parents=True)
    (mods / "views").mkdir(parents=True)
    (mods / "hooks.py").write_text(
        textwrap.dedent(
            """
            def install(env):
                from pyvelm.security import grant_model_access
                grant_model_access(env, "v13test.widget", admin="crud", user="crud")
            """
        ),
        encoding="utf-8",
    )
    (mods / "__pyvelm__.py").write_text(
        textwrap.dedent(
            """
            from pyvelm.manifest import Manifest
            manifest = (
                Manifest.make("v13test")
                .version(0, 1, 0)
                .depends("base", "admin")
                .data("views/widget.py")
                .install_hook("v13test.hooks:install")
            )
            """
        ),
        encoding="utf-8",
    )
    (mods / "models" / "__init__.py").write_text(
        "from . import widget  # noqa: F401\n", encoding="utf-8"
    )
    (mods / "models" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm import BaseModel, Boolean, Char, Integer

            class Widget(BaseModel):
                _name = "v13test.widget"
                name = Char()
                active = Boolean(default=True)
                sequence = Integer(default=10)
            """
        ),
        encoding="utf-8",
    )
    (mods / "views" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm.builders import DetailView, FormView, ListView, ViewsData

            views_data = ViewsData.make().views(
                ListView.make("widget.list")
                .model("v13test.widget")
                .columns(["name", "active"])
                .detail_view("widget.detail"),
                DetailView.make("widget.detail")
                .model("v13test.widget")
                .form_view("widget.form")
                .section("main", "Main", ["name"]),
                FormView.make("widget.form")
                .model("v13test.widget")
                .section("main", "Main", ["name"]),
                ListView.make("widget.seq")
                .model("v13test.widget")
                .columns(["name"])
                .sequence("sequence"),
                ListView.make("widget.archive")
                .model("v13test.widget")
                .columns(["name"])
                .bulk_actions(
                    [{"action": "archive", "label": "Archive", "perm": "write"}]
                ),
            )
            """
        ),
        encoding="utf-8",
    )
    return [root / "modules"]


@pytest.fixture(scope="module")
def v13_module_roots(tmp_path_factory):
    purge_import_prefix("v13test")
    root = tmp_path_factory.mktemp("v13mod")
    return BUILTIN_MODULE_ROOTS + _write_v13_module(root)


@pytest.fixture
def v13_client(pyvelm_dsn: str, v13_module_roots):
    purge_import_prefix("v13test")
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        install_named_modules(env, ["admin", "v13test"], v13_module_roots)
        Widget = env["v13test.widget"]
        ids = {
            "a": Widget.create({"name": "Alpha", "active": True}).id,
            "b": Widget.create({"name": "Bravo", "active": False}).id,
        }
    app = create_app(reg, db, module_roots=v13_module_roots)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.auth = ("admin", "admin")
        yield client, db, reg, ids
    db.dispose()


@pytest.mark.integration
class TestV13WebIntegration:
    def test_list_page_renders_bulk_ui(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.get("/web/views/v13test/widget.list")
        assert resp.status_code == 200
        assert "bulkEnabled" in resp.text
        assert 'type="checkbox"' in resp.text

    def test_detail_view_display(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.get(
            f"/web/views/v13test/widget.detail/record/{ids['a']}"
        )
        assert resp.status_code == 200
        assert "Alpha" in resp.text
        assert "Edit" in resp.text

    def test_form_bare_url_still_unsupported(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.get("/web/views/v13test/widget.form")
        assert resp.status_code == 501

    def test_bulk_unlink_deletes_rows(self, v13_client):
        client, db, reg, ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            json={"action": "unlink", "ids": [ids["b"]]},
        )
        assert resp.status_code in (200, 303)
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            remaining = env["v13test.widget"].search([("id", "=", ids["b"])])
            assert not remaining

    def test_bulk_hx_redirect(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            json={"action": "unlink", "ids": [ids["b"]]},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/web/views/v13test/widget.list"

    def test_bulk_invalid_body(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            content="not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_bulk_requires_ids(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            json={"action": "unlink", "ids": []},
        )
        assert resp.status_code == 400

    def test_bulk_invalid_ids(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            json={"action": "unlink", "ids": ["x"]},
        )
        assert resp.status_code == 400

    def test_bulk_denied_action(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.list/bulk",
            json={"action": "archive", "ids": [ids["a"]]},
        )
        assert resp.status_code == 403

    def test_bulk_not_list_view(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.detail/bulk",
            json={"action": "unlink", "ids": [ids["a"]]},
        )
        assert resp.status_code == 400

    def test_list_rows_fragment_includes_bulk(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.get(
            "/web/records/v13test/widget.list",
            params={"page": 0, "page_size": 10},
        )
        assert resp.status_code == 200
        assert "Alpha" in resp.text

    def test_list_group_by_uses_build_list_rows(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.get(
            "/web/records/v13test/widget.list",
            params={"page": 0, "page_size": 10, "group_by": "active"},
        )
        assert resp.status_code == 200
        assert "Alpha" in resp.text or "Bravo" in resp.text

    def test_sequence_list_disables_bulk(self, v13_client):
        client, _db, _reg, _ids = v13_client
        resp = client.get("/web/views/v13test/widget.seq")
        assert resp.status_code == 200
        assert "bulkEnabled:false" in resp.text.replace(" ", "")

    def test_render_list_page_sequence_path(self, pyvelm_dsn, v13_module_roots):
        purge_import_prefix("v13test")
        reset_database(pyvelm_dsn)
        reg = Registry()
        db = open_database(pyvelm_dsn, pool_size=2)
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            install_named_modules(env, ["admin", "v13test"], v13_module_roots)
            env["v13test.widget"].create({"name": "SeqRow", "sequence": 10})
            View = env["ir.ui.view"]
            seq_view = View.search(
                [("module", "=", "v13test"), ("name", "=", "widget.seq")],
                limit=1,
            )
            seq_view.ensure_one()
            html = render_list_page(seq_view, env, page=0, page_size=10)
            assert "bulkEnabled:false" in html.replace(" ", "")
            frag = render_list_rows(seq_view, env, page=0, page_size=10)
            assert "data-pv-row-handle" in frag
        db.dispose()

    def test_bulk_unauthenticated(self, pyvelm_dsn, v13_module_roots):
        purge_import_prefix("v13test")
        reset_database(pyvelm_dsn)
        reg = Registry()
        db = open_database(pyvelm_dsn, pool_size=2)
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            install_named_modules(env, ["admin", "v13test"], v13_module_roots)
            ids = {
                "a": env["v13test.widget"].create({"name": "Alpha"}).id,
            }
        app = create_app(reg, db, module_roots=v13_module_roots)
        with TestClient(app, raise_server_exceptions=False) as anon:
            resp = anon.post(
                "/web/records/v13test/widget.list/bulk",
                json={"action": "unlink", "ids": [ids["a"]]},
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 204
            assert "/login" in (resp.headers.get("HX-Redirect") or "")
        db.dispose()

    def test_bulk_unlink_second_permission_gate(self, v13_client):
        client, _db, _reg, ids = v13_client
        real_has_access = Environment.has_access
        unlink_checks = {"count": 0}

        def allow_then_deny_unlink(self, model, perm):
            if model == "v13test.widget" and perm == "unlink":
                unlink_checks["count"] += 1
                return unlink_checks["count"] == 1
            return real_has_access(self, model, perm)

        with patch.object(Environment, "has_access", allow_then_deny_unlink):
            resp = client.post(
                "/web/records/v13test/widget.list/bulk",
                json={"action": "unlink", "ids": [ids["a"]]},
                headers={"Accept": "application/json"},
            )
        assert resp.status_code == 403

    def test_bulk_unknown_action(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.post(
            "/web/records/v13test/widget.archive/bulk",
            json={"action": "archive", "ids": [ids["a"]]},
        )
        assert resp.status_code == 400

    def test_form_display_rejects_list_view(self, v13_client):
        client, _db, _reg, ids = v13_client
        resp = client.get(
            f"/web/views/v13test/widget.list/record/{ids['a']}"
        )
        assert resp.status_code == 400

    def test_detail_view_requires_read_access(self, v13_client):
        client, _db, _reg, ids = v13_client
        real_has_access = Environment.has_access

        def deny_widget_read(self, model, perm):
            if model == "v13test.widget" and perm == "read":
                return False
            return real_has_access(self, model, perm)

        with patch.object(Environment, "has_access", deny_widget_read):
            resp = client.get(
                f"/web/views/v13test/widget.detail/record/{ids['a']}"
            )
        assert resp.status_code == 403


@pytest.mark.integration
def test_render_list_helpers(pyvelm_dsn: str, v13_module_roots):
    purge_import_prefix("v13test")
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        install_named_modules(env, ["admin", "v13test"], v13_module_roots)
        Widget = env["v13test.widget"]
        w = Widget.create({"name": "RenderMe"})
        View = env["ir.ui.view"]
        list_view = View.search(
            [("module", "=", "v13test"), ("name", "=", "widget.list")],
            limit=1,
        )
        list_view.ensure_one()
        html = render_list_page(list_view, env, page=0, page_size=10)
        assert "RenderMe" in html
        assert "bulkEnabled" in html
        grouped = render_list_page(
            list_view, env, page=0, page_size=10, group_by="active"
        )
        assert "RenderMe" in grouped or "Yes" in grouped
        frag = render_list_rows(
            list_view, env, page=0, page_size=10, group_by="active"
        )
        assert "RenderMe" in frag or "Yes" in frag
        detail_view = View.search(
            [("module", "=", "v13test"), ("name", "=", "widget.detail")],
            limit=1,
        )
        html_detail = render_form_page(
            detail_view, w, env, mode="display"
        )
        assert "RenderMe" in html_detail
        assert "Edit" in html_detail
    db.dispose()


if __name__ == "__main__":
    unittest.main()
