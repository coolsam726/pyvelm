"""View-action inline forms (ActionForm / ``/web/view-actions/...``)."""
from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry
from pyvelm.builders import Action, ActionForm, Field
from pyvelm.tests._isolation import purge_import_prefix
from pyvelm.tests.support.db import install_named_modules, open_database, reset_database
from pyvelm.view_actions import view_action_key
from pyvelm.web import create_app


class ActionBuilderTests(unittest.TestCase):
    def test_action_form_serializes_sections(self):
        arch = (
            Action.make("Quick add")
            .model("res.partner")
            .perm("create")
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
        self.assertEqual(len(arch["form"]["sections"]), 1)
        self.assertEqual(arch["form"]["sections"][0]["fields"][0], {"name": "name"})

    def test_view_action_key_slug(self):
        self.assertEqual(view_action_key("Quick add"), "quick-add")
        self.assertEqual(view_action_key("Load demo data!"), "load-demo-data")


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
                grant_model_access(env, "actiontest.widget", admin="crud", user="crud")
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
        "from . import widget  # noqa: F401\n", encoding="utf-8"
    )
    (mods / "models" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm import BaseModel, Boolean, Char

            class Widget(BaseModel):
                _name = "actiontest.widget"
                name = Char(required=True)
                active = Boolean(default=True)
            """
        ),
        encoding="utf-8",
    )
    (mods / "views" / "widget.py").write_text(
        textwrap.dedent(
            """
            from pyvelm.builders import Action, ActionForm, Field, ListView, ViewsData

            views_data = ViewsData.make().views(
                ListView.make("widget.list")
                .model("actiontest.widget")
                .columns(["name"])
                .page_actions([
                    Action.make("Quick add")
                    .model("actiontest.widget")
                    .perm("create")
                    .form(
                        ActionForm.make().section(
                            "main", "Main", ["name", Field.make("active").toggle()]
                        )
                    ),
                ]),
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
    def test_form_get_renders_fields(self, action_client):
        client, _db, _reg = action_client
        resp = client.get(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form"
        )
        assert resp.status_code == 200
        assert "Quick add" in resp.text
        assert 'name="name"' in resp.text
        assert "data-pv-inline-action-form" in resp.text

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

    def test_form_post_empty_body_422(self, action_client):
        client, _db, _reg = action_client
        resp = client.post(
            "/web/view-actions/actiontest/widget.list/page/quick-add/form",
            json={},
        )
        assert resp.status_code == 422

    def test_unknown_action_404(self, action_client):
        client, _db, _reg = action_client
        resp = client.get(
            "/web/view-actions/actiontest/widget.list/page/missing/form"
        )
        assert resp.status_code == 404

    def test_list_page_renders_inline_action_button(self, action_client):
        client, _db, _reg = action_client
        resp = client.get("/web/views/actiontest/widget.list")
        assert resp.status_code == 200
        assert "quick-add/form" in resp.text
        assert "PvDialog.open" in resp.text


@pytest.mark.integration
class TestListRowSelectionTemplate:
    def test_list_row_uses_set_row_selected(self, action_client):
        client, _db, _reg = action_client
        resp = client.get("/web/views/actiontest/widget.list")
        assert "setRowSelected" in resp.text
        assert "toggleRow" not in resp.text
