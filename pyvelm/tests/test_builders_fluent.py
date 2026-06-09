"""Tests for fluent view/menu builder classes."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from pyvelm import loader
from pyvelm.builders import (
    Field,
    FormView,
    InheritView,
    ListView,
    Menus,
    ViewsData,
    flatten_menus,
    op_remove,
)


class FluentBuilderTests(unittest.TestCase):
    def test_list_view_to_dict(self):
        view = (
            ListView.make("partner.list")
            .model("res.partner")
            .columns(["name", Field.make("active").toggle()])
            .form_view("partner.form")
        )
        d = view.to_dict()
        self.assertEqual(d["name"], "partner.list")
        self.assertEqual(d["arch"]["fields"][1]["widget"], "toggle")

    def test_form_view_sections(self):
        view = (
            FormView.make("partner.form")
            .model("res.partner")
            .section("identity", "Identity", ["name", "code"])
        )
        d = view.to_dict()
        self.assertEqual(d["arch"]["sections"][0]["name"], "identity")

    def test_views_data_round_trip(self):
        m = Menus("demo")
        vd = (
            ViewsData.make()
            .views(
                ListView.make("item.list").model("demo.item").columns(["name"]),
            )
            .menus(
                m.group("app", "App", icon="home").children([
                    m.item("app.items", "Items").view("item.list"),
                ])
            )
        )
        data = vd.to_dict()
        self.assertEqual(len(data["VIEWS"]), 1)
        self.assertEqual(data["MENUS"][1]["href"], "/web/views/demo/item.list")

    def test_loader_reads_views_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            root.mkdir()
            (root / "__init__.py").write_text("", encoding="utf-8")
            (root / "__pyvelm__.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.manifest import Manifest
                    manifest = Manifest.make("demo").version(0, 1, 0)
                    """
                ),
                encoding="utf-8",
            )
            (root / "views").mkdir()
            (root / "views" / "item.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.builders import ViewsData, ListView

                    views_data = ViewsData.make().views(
                        ListView.make("item.list").model("demo.item").columns(["name"]),
                    )
                    """
                ),
                encoding="utf-8",
            )
            (root / "__pyvelm__.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm.manifest import Manifest
                    manifest = (
                        Manifest.make("demo")
                        .version(0, 1, 0)
                        .data("views/item.py")
                    )
                    """
                ),
                encoding="utf-8",
            )
            spec = loader.discover([Path(tmp)])["demo"]
            loader._load_data_files(spec)
            self.assertEqual(spec.views[0]["name"], "item.list")

    def test_inherit_view(self):
        inherit = (
            InheritView.make("partner.list.ext")
            .extends("partners.partner.list")
            .operation(op_remove(["fields", "age"]))
        )
        d = inherit.to_dict()
        self.assertEqual(d["inherit"], "partners.partner.list")
        self.assertEqual(d["operations"][0]["op"], "remove")

    def test_menu_item_fluent(self):
        m = Menus("partners")
        menus = flatten_menus([
            m.group("business", "Business").children([
                m.item("business.partners", "Partners").view("partner.list"),
            ])
        ])
        self.assertEqual(menus[1]["href"], "/web/views/partners/partner.list")
