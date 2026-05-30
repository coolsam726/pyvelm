"""Automatic display_name on every model."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Environment, Registry, Text
from pyvelm.tests.support.db import DatabaseTestCase


class DisplayNameFieldTests(unittest.TestCase):
    def test_injected_on_models_with_name(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.dn.partner"
                name = Char()

        self.assertIn("display_name", Partner._fields)
        self.assertEqual(
            Partner._fields["display_name"].depends_on,
            ("name",),
        )

    def test_rec_name_override(self):
        reg = Registry()
        with reg.activate():

            class Comment(BaseModel):
                _name = "test.dn.comment"
                _rec_name = "body"
                body = Text()

        self.assertEqual(
            Comment._fields["display_name"].depends_on,
            ("body",),
        )

    def test_missing_rec_name_field_depends_on_id(self):
        reg = Registry()
        with reg.activate():

            class Note(BaseModel):
                _name = "test.dn.note"
                body = Text()

        self.assertIn("id", Note._fields)
        self.assertEqual(
            Note._fields["display_name"].depends_on,
            ("id",),
        )
        reg._build_compute_graph()

    def test_id_parse_path_for_compute_graph(self):
        from pyvelm.paths import parse_path

        reg = Registry()
        with reg.activate():

            class Note(BaseModel):
                _name = "test.dn.note2"
                body = Text()

        path = parse_path(Note, "id", reg)
        self.assertEqual(path.leaf_attr, "id")
        reg._build_compute_graph()

    def test_explicit_display_name_not_duplicated(self):
        from pyvelm import depends

        reg = Registry()
        with reg.activate():

            class Custom(BaseModel):
                _name = "test.dn.custom"
                name = Char()
                display_name = Char(compute="_compute_display_name")

                @depends("name")
                def _compute_display_name(self):
                    for r in self:
                        r.display_name = f"*{r.name}*"

        self.assertEqual(Custom._fields["display_name"].depends_on, ("name",))


class DisplayNameRuntimeTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_default_and_rec_name(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.dn.item"
                label = Char()

            class Tagged(BaseModel):
                _name = "test.dn.tagged"
                _rec_name = "label"
                label = Char()

        reg.init_db(self.conn)
        self.conn.commit()
        env = Environment(self.conn, reg, uid=1)
        item = env["test.dn.item"].create({"label": "ignored"})
        tagged = env["test.dn.tagged"].create({"label": "Hello"})
        self.assertEqual(item.display_name, "test.dn.item #1")
        self.assertEqual(tagged.display_name, "Hello")


if __name__ == "__main__":
    unittest.main()
