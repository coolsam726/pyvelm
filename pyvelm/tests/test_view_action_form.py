"""View-action inline forms (ActionForm / ``/web/view-actions/...``)."""
from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pyvelm import BUILTIN_MODULE_ROOTS, Char, Environment, Registry
from pyvelm.builders.action import Action, ActionForm, action_specs
from pyvelm.builders import Field
from pyvelm.tests._isolation import purge_import_prefix
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database
from pyvelm.view_actions import (
    ViewActionLocator,
    inline_action_form_fields,
    render_view_action_inline_form,
    view_action_form_url,
    view_action_key,
)
from pyvelm.web import create_app


class ActionFormBuilderTests(unittest.TestCase):
    def test_cols_and_model_on_arch(self):
        arch = (
            ActionForm.make()
            .model("res.partner")
            .cols(2)
            .section("main", "Main", ["name"])
            .to_dict()
        )
        self.assertEqual(arch["model"], "res.partner")
        self.assertEqual(arch["cols"], 2)
        self.assertEqual(arch["sections"][0]["cols"], 2)


class ActionBuilderTests(unittest.TestCase):
    def test_action_form_serializes_sections(self):
        arch = (
            Action.make("Quick add")
            .model("res.partner")
            .perm("create")
            .confirm("Sure?")
            .method("POST")
            .policy("approve")
            .full_page(True)
            .form(
                ActionForm.make().section(
                    "main",
                    "Main",
                    ["name", Field.make("active").toggle()],
                )
            )
            .to_dict()
        )
        self.assertEqual(arch["label"], "Quick add")
        self.assertEqual(arch["model"], "res.partner")
        self.assertEqual(arch["perm"], "create")
        self.assertEqual(arch["confirm"], "Sure?")
        self.assertEqual(arch["method"], "POST")
        self.assertEqual(arch["policy"], "approve")
        self.assertTrue(arch["full_page"])
        self.assertEqual(len(arch["form"]["sections"]), 1)

    def test_model_from_action_form(self):
        arch = (
            Action.make("Quick add")
            .form(
                ActionForm.make()
                .model("res.partner")
                .section("main", "Main", ["name"])
            )
            .to_dict()
        )
        self.assertEqual(arch["model"], "res.partner")

    def test_form_view_action(self):
        arch = (
            Action.make("Open form")
            .form_view("partner.form", "partners")
            .to_dict()
        )
        self.assertEqual(arch["form_view"], "partner.form")
        self.assertEqual(arch["form_module"], "partners")

    def test_url_action(self):
        arch = Action.make("Export").url("/export").method("get").to_dict()
        self.assertEqual(arch["url"], "/export")
        self.assertEqual(arch["method"], "GET")

    def test_callable_form_builder(self):
        arch = (
            Action.make("Quick add")
            .model("x.model")
            .form(lambda f: f.section("main", "Main", ["name"]))
            .to_dict()
        )
        self.assertIn("form", arch)

    def test_empty_sections_raises(self):
        with self.assertRaises(ValueError):
            Action.make("Bad").form(ActionForm.make())

    def test_orphan_action_raises(self):
        with self.assertRaises(ValueError):
            Action.make("Orphan").to_dict()

    def test_inline_without_model_raises(self):
        with self.assertRaises(ValueError):
            (
                Action.make("Inline")
                .form(ActionForm.make().section("main", "Main", ["name"]))
                .to_dict()
            )

    def test_empty_label_raises(self):
        action = Action.make("")
        action._label = ""
        with self.assertRaises(ValueError):
            action.to_dict()


class ActionSpecsTests(unittest.TestCase):
    def test_normalizes_action_instances_and_dicts(self):
        out = action_specs(
            [
                Action.make("A").url("/a"),
                {"label": "B", "url": "/b"},
            ]
        )
        self.assertEqual(out[0]["label"], "A")
        self.assertEqual(out[1]["url"], "/b")


class ViewActionKeyTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(view_action_key("Quick add"), "quick-add")
        self.assertEqual(view_action_key("Load demo data!"), "load-demo-data")

    def test_form_url_with_record(self):
        self.assertEqual(
            view_action_form_url("partners", "partner.list", "page", "quick-add"),
            "/web/view-actions/partners/partner.list/page/quick-add/form",
        )
        self.assertEqual(
            view_action_form_url(
                "partners", "partner.detail", "header", "quick-edit", 42
            ),
            "/web/view-actions/partners/partner.detail/header/quick-edit/form?record=42",
        )


class ViewActionLocatorTests(unittest.TestCase):
    def _locate(self, arch: dict, slot: str, key: str):
        view = SimpleNamespace()
        env = MagicMock()
        with patch("pyvelm.render._load_ui_view", return_value=view):
            with patch("pyvelm.view_actions.resolve_arch", return_value=arch):
                return ViewActionLocator().find(
                    env, "actiontest", "widget.list", slot, key
                )

    def test_find_page_action(self):
        action = self._locate(
            {
                "page_actions": [
                    {"label": "Quick add", "form": {"sections": []}},
                ]
            },
            "page",
            "quick-add",
        )
        self.assertEqual(action["label"], "Quick add")

    def test_page_actions_slot_alias(self):
        action = self._locate(
            {"page_actions": [{"label": "Quick add"}]},
            "page_actions",
            "quick-add",
        )
        self.assertIsNotNone(action)

    def test_header_actions_slot(self):
        action = self._locate(
            {"header_actions": [{"label": "Quick edit"}]},
            "header_actions",
            "quick-edit",
        )
        self.assertEqual(action["label"], "Quick edit")

    def test_unknown_slot_returns_none(self):
        self.assertIsNone(
            self._locate({"page_actions": []}, "bulk", "x")
        )

    def test_missing_view_returns_none(self):
        env = MagicMock()
        with patch("pyvelm.render._load_ui_view", return_value=None):
            self.assertIsNone(
                ViewActionLocator().find(env, "x", "y", "page", "z")
            )

    def test_skips_non_dict_actions(self):
        action = self._locate(
            {"page_actions": ["bad", {"label": "Quick add"}]},
            "page",
            "quick-add",
        )
        self.assertEqual(action["label"], "Quick add")

    def test_no_match_returns_none(self):
        self.assertIsNone(
            self._locate({"page_actions": [{"label": "Other"}]}, "page", "nope")
        )


class InlineActionFormFieldsUnitTests(unittest.TestCase):
    def test_custom_label_and_text_widget_on_char(self):
        env = MagicMock()
        char_field = Char(string="Name")
        char_field.bind("x.model", "name")
        model_cls = SimpleNamespace(_fields={"name": char_field})
        env.registry = {"x.model": model_cls}

        fields = inline_action_form_fields(
            env,
            "x.model",
            {
                "sections": [
                    {
                        "fields": [
                            {"name": "name", "label": "Custom"},
                            {"name": "bio", "widget": "text"},
                        ]
                    }
                ]
            },
        )
        self.assertEqual(fields[0]["label"], "Custom")
        self.assertEqual(fields[1]["type"], "text")
        self.assertTrue(fields[1]["multiline"])

    def test_notebook_pages_and_invalid_specs(self):
        env = MagicMock()
        model_cls = SimpleNamespace(_fields={})
        env.registry = {"x.model": model_cls}

        fields = inline_action_form_fields(
            env,
            "x.model",
            {
                "sections": [
                    "not-a-section",
                    {
                        "name": "nb",
                        "pages": [
                            "not-a-page",
                            {"name": "p1", "fields": ["alpha", 42, {"nope": True}]},
                        ],
                    },
                    {"name": "flat", "fields": ["beta"]},
                ]
            },
            {"alpha": "A", "beta": "B"},
        )
        names = [f["name"] for f in fields]
        self.assertEqual(names, ["alpha", "beta"])


class RenderInlineFormTests(unittest.TestCase):
    def test_renders_template(self):
        html = render_view_action_inline_form(
            title="Quick add",
            fields=[
                {
                    "name": "name",
                    "label": "Name",
                    "type": "char",
                    "required": True,
                    "value": "Acme",
                }
            ],
            submit_url="/web/view-actions/x/y/page/z/form",
            record_id=0,
        )
        self.assertIn("Quick add", html)
        self.assertIn("data-pv-inline-action-form", html)
        self.assertIn("Create", html)

    def test_save_label_when_editing(self):
        html = render_view_action_inline_form(
            title="Edit",
            fields=[],
            submit_url="/web/view-actions/x/y/header/z/form?record=3",
            record_id=3,
        )
        self.assertIn("Save", html)


class ResolveViewActionTests(unittest.TestCase):
    def test_inline_form_enriched_with_form_url(self):
        from pyvelm.render import _resolve_header_actions

        acts = _resolve_header_actions(
            [
                {
                    "label": "Quick add",
                    "model": "res.partner",
                    "perm": "create",
                    "form": {
                        "sections": [
                            {
                                "name": "main",
                                "title": "Main",
                                "fields": [{"name": "name"}],
                            }
                        ]
                    },
                }
            ],
            _FakeEnv(),
            model="res.partner",
            module="partners",
            name="partner.list",
            record_id=0,
            slot="page",
        )
        self.assertEqual(len(acts), 1)
        act = acts[0]
        self.assertEqual(act["kind"], "inline_form")
        self.assertEqual(
            act["form_url"],
            "/web/view-actions/partners/partner.list/page/quick-add/form",
        )

    def test_header_inline_includes_record_query(self):
        from pyvelm.render import _resolve_header_actions

        acts = _resolve_header_actions(
            [
                {
                    "label": "Quick edit",
                    "model": "res.partner",
                    "perm": "write",
                    "form": {
                        "sections": [{"name": "m", "fields": [{"name": "name"}]}]
                    },
                }
            ],
            _FakeEnv(),
            model="res.partner",
            module="partners",
            name="partner.detail",
            record_id=9,
            slot="header",
        )
        self.assertIn("?record=9", acts[0]["form_url"])

    def test_get_and_post_kinds(self):
        from pyvelm.render import _resolve_header_actions

        env = _FakeEnv()
        out = _resolve_header_actions(
            [
                {
                    "label": "Export",
                    "url": "/web/views/partners/partner.list/export",
                    "method": "GET",
                },
                {"label": "Run", "url": "/web/run", "method": "POST"},
            ],
            env,
            model="res.partner",
            module="partners",
            name="partner.list",
            record_id=0,
            slot="page",
        )
        self.assertEqual(out[0]["kind"], "get")
        self.assertEqual(out[1]["kind"], "post")

    def test_skips_action_without_url_or_form(self):
        from pyvelm.render import _resolve_header_actions

        out = _resolve_header_actions(
            [{"label": "Empty"}],
            _FakeEnv(),
            model="res.partner",
            module="partners",
            name="partner.list",
            record_id=0,
            slot="page",
        )
        self.assertEqual(out, [])


class _FakeEnv:
    def has_access(self, model, perm):
        return True

    def can(self, record, policy, perm=None):
        return True


def _write_action_module(root: Path) -> list[Path]:
    mods = root / "modules" / "actiontest"
    (mods / "models").mkdir(parents=True)
    (mods / "views").mkdir(parents=True)
    (mods / "hooks.py").write_text(
        textwrap.dedent(
            """
            def install(env):
                from pyvelm.security import grant_model_access
                grant_model_access(env, "actiontest.widget", admin="crud", user="read")
                grant_model_access(env, "actiontest.tag", admin="crud", user="read")
            """
        ),
        encoding="utf-8",
    )
    (mods / "__pyvelm__.py").write_text(
        textwrap.dedent(
            """
            from pyvelm.manifest import Manifest
            manifest = (
                Manifest.make("actiontest")
                .version(0, 1, 0)
                .depends("base", "admin")
                .data("views/widget.py")
                .install_hook("actiontest.hooks:install")
            )
            """
        ),
        encoding="utf-8",
    )
    (mods / "models" / "__init__.py").write_text(
        "from . import tag, widget  # noqa: F401\n", encoding="utf-8"
    )
    (mods / "models" / "tag.py").write_text(
        textwrap.dedent(
            """
            from pyvelm import BaseModel, Char

            class Tag(BaseModel):
                _name = "actiontest.tag"
                name = Char(required=True)
            """
        ),
        encoding="utf-8",
    )
    (mods / "models" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm import BaseModel, Boolean, Char, Float, Integer, Many2one, Text

            class Widget(BaseModel):
                _name = "actiontest.widget"
                name = Char(required=True)
                active = Boolean(default=True)
                tag_id = Many2one("actiontest.tag")
                notes = Text()
                qty = Integer()
                score = Float()
            """
        ),
        encoding="utf-8",
    )
    (mods / "views" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm.builders import Action, ActionForm, Field, FormView, ListView, ViewsData

            views_data = ViewsData.make().views(
                ListView.make("widget.list")
                .model("actiontest.widget")
                .columns(["name", "tag_id"])
                .page_actions([
                    Action.make("Quick add")
                    .model("actiontest.widget")
                    .perm("create")
                    .form(
                        ActionForm.make().section(
                            "main",
                            "Main",
                            [
                                "name",
                                "tag_id",
                                "notes",
                                "qty",
                                "score",
                                Field.make("active").toggle(),
                            ],
                        )
                    ),
                    Action.make("Export CSV")
                    .url("/web/demo/export")
                    .method("GET")
                    .perm("read"),
                ]),
                FormView.make("widget.form")
                .model("actiontest.widget")
                .header_actions([
                    Action.make("Quick edit")
                    .model("actiontest.widget")
                    .perm("write")
                    .form(
                        ActionForm.make().section(
                            "main", "Main", ["name", Field.make("active").toggle()]
                        )
                    ),
                ])
                .section("main", "Main", ["name", "tag_id", "notes", "qty", "score"]),
            )
            """
        ),
        encoding="utf-8",
    )
    return [root / "modules"]


@pytest.fixture(scope="module")
def action_module_roots(tmp_path_factory):
    purge_import_prefix("actiontest")
    root = tmp_path_factory.mktemp("actionmod")
    return BUILTIN_MODULE_ROOTS + _write_action_module(root)


@pytest.fixture
def action_client(pyvelm_dsn: str, action_module_roots):
    purge_import_prefix("actiontest")
    reset_database(pyvelm_dsn)
    reg = Registry()
    db = open_database(pyvelm_dsn, pool_size=2)
    with db.connect() as conn:
        env = Environment(conn, registry=reg, uid=1)
        install_named_modules(env, ["admin", "actiontest"], action_module_roots)
    app = create_app(reg, db, module_roots=action_module_roots)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.auth = ("admin", "admin")
        yield client, db, reg
    db.dispose()


@pytest.mark.integration
class TestViewActionFormWeb:
    def test_form_get_renders_all_field_kinds(self, action_client):
        client, db, reg = action_client
        form_arch = {
            "sections": [
                {
                    "name": "main",
                    "fields": [
                        "name",
                        "tag_id",
                        "notes",
                        "qty",
                        "score",
                        {"name": "active", "widget": "toggle"},
                    ],
                }
            ]
        }
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            env["actiontest.tag"].create({"name": "VIP"})
            tag_id = env["actiontest.tag"].search([], limit=1).id
            widget_id = env["actiontest.widget"].create(
                {
                    "name": "Loaded",
                    "tag_id": tag_id,
                    "notes": "Hello",
                    "qty": 3,
                    "score": 1.5,
                }
            ).id
            fields = inline_action_form_fields(
                env,
                "actiontest.widget",
                form_arch,
                env["actiontest.widget"].browse(widget_id).read()[0],
            )
        kinds = {f["type"] for f in fields}
        assert kinds >= {"char", "many2one", "text", "integer", "boolean"}
        assert any(f["name"] == "score" for f in fields)

        resp = client.get(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form"
        )
        assert resp.status_code == 200
        assert "Quick add" in resp.text
        assert 'name="name"' in resp.text
        assert "<select" in resp.text
        assert "<textarea" in resp.text
        assert 'type="number"' in resp.text
        assert "data-pv-inline-action-form" in resp.text

        edit = client.get(
            "/web/view-actions/actiontest/widget.form/header/quick-edit/form"
            f"?record={widget_id}"
        )
        assert edit.status_code == 200
        assert "Loaded" in edit.text
        assert "Save" in edit.text

    def test_form_post_creates_record(self, action_client):
        client, db, reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form",
            json={"name": "Inline Widget", "active": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            found = env["actiontest.widget"].search(
                [("name", "=", "Inline Widget")]
            )
            assert len(found) == 1

    def test_form_post_updates_record(self, action_client):
        client, db, reg = action_client
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            wid = env["actiontest.widget"].create({"name": "Before"}).id
        resp = client.post(
            f"/web/view-actions/actiontest/widget.form/header/quick-edit/form?record={wid}",
            json={"name": "After", "active": False},
        )
        assert resp.status_code == 200
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            row = env["actiontest.widget"].browse(wid).read(["name", "active"])[0]
            assert row["name"] == "After"
            assert row["active"] is False

    def test_form_post_empty_body_422(self, action_client):
        client, _db, _reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form",
            json={},
        )
        assert resp.status_code == 422

    def test_form_post_invalid_json_422(self, action_client):
        client, _db, _reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_form_post_write_validation_422(self, action_client):
        client, _db, _reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form",
            json={"active": True},
        )
        assert resp.status_code == 422

    def test_unknown_action_404(self, action_client):
        client, _db, _reg = action_client
        resp = client.get(
            "/web/view-actions/actiontest/widget.list/page/missing/form"
        )
        assert resp.status_code == 404

    def test_url_only_action_has_no_inline_form(self, action_client):
        client, _db, _reg = action_client
        resp = client.get(
            "/web/view-actions/actiontest/widget.list/page/export-csv/form"
        )
        assert resp.status_code == 404
        assert "inline form" in resp.text.lower()

    def test_post_unknown_action_json_404(self, action_client):
        client, _db, _reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/missing/form",
            json={"name": "X"},
        )
        assert resp.status_code == 404

    def test_list_page_renders_inline_action_button(self, action_client):
        client, _db, _reg = action_client
        resp = client.get("/web/views/actiontest/widget.list")
        assert resp.status_code == 200
        assert "quick-add/form" in resp.text
        assert "PvDialog.open" in resp.text

    def test_get_denied_without_create(self, action_client):
        client, _db, _reg = action_client
        real_check = Environment.check_access

        def deny_create(self, model, perm):
            if model == "actiontest.widget" and perm == "create":
                raise PermissionError("nope")
            return real_check(self, model, perm)

        with patch.object(Environment, "check_access", deny_create):
            resp = client.get(
                "/web/view-actions/actiontest/widget.list/page/quick-add/form"
            )
        assert resp.status_code == 403

    def test_post_denied_without_create(self, action_client):
        client, _db, _reg = action_client
        real_check = Environment.check_access

        def deny_create(self, model, perm):
            if model == "actiontest.widget" and perm == "create":
                raise PermissionError("nope")
            return real_check(self, model, perm)

        with patch.object(Environment, "check_access", deny_create):
            resp = client.post(
                "/web/view-actions/actiontest/widget.list/page/quick-add/form",
                json={"name": "Denied"},
            )
        assert resp.status_code == 403

    def test_unauthenticated_get_redirects(self, action_client, pyvelm_dsn, action_module_roots):
        client, db, reg = action_client
        db.dispose()
        app = create_app(reg, db, module_roots=action_module_roots)
        with TestClient(app, raise_server_exceptions=False) as anon:
            resp = anon.get(
                "/web/view-actions/actiontest/widget.list/page/quick-add/form",
                headers={"HX-Request": "true"},
            )
        assert resp.status_code == 204
        assert "/login" in (resp.headers.get("HX-Redirect") or "")

@pytest.mark.integration
class TestInlineActionFormFieldsIntegration:
    def test_non_scalar_value_json_encoded(self, action_client):
        _client, db, reg = action_client
        with db.connect() as conn:
            env = Environment(conn, registry=reg, uid=1)
            fields = inline_action_form_fields(
                env,
                "actiontest.widget",
                {
                    "sections": [
                        {
                            "name": "main",
                            "fields": ["score"],
                        }
                    ]
                },
                {"score": {"bad": True}},
            )
        score = next(f for f in fields if f["name"] == "score")
        assert score["type"] == "char"
        assert score["value"] == '{"bad": true}'


@pytest.mark.integration
class TestListRowSelectionTemplate:
    def test_list_row_uses_set_row_selected(self, action_client):
        client, _db, _reg = action_client
        resp = client.get("/web/views/actiontest/widget.list")
        assert "setRowSelected" in resp.text
        assert "toggleRow" not in resp.text
        assert "x-effect" in resp.text
