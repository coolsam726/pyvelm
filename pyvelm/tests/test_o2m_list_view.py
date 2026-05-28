"""Per-field list_view / form_view for embedded One2many tables."""

import unittest

from pyvelm import BaseModel, Char, One2many
from pyvelm.registry import Registry
from pyvelm.render import _resolve_o2m_table_fields
class O2mListViewRefTests(unittest.TestCase):
    def test_one2many_field_stores_list_view(self):
        reg = Registry()
        with reg.activate():

            class Line(BaseModel):
                _name = "test.o2m.line"
                parent_id = Char()

            class Parent(BaseModel):
                _name = "test.o2m.parent"
                line_ids = One2many(
                    "test.o2m.line",
                    "parent_id",
                    list_view="test.o2m.line.invoice",
                    form_view=("acct", "line.form"),
                )

        field = reg["test.o2m.parent"]._fields["line_ids"]
        self.assertEqual(field.list_view, "test.o2m.line.invoice")
        self.assertEqual(field.form_view, ("acct", "line.form"))

    def test_inline_columns_without_list_view(self):
        reg = Registry()
        with reg.activate():

            class Line(BaseModel):
                _name = "inline.line"
                name = Char()
                body = Char()
                secret = Char()

            class Parent(BaseModel):
                _name = "inline.parent"
                line_ids = One2many("inline.line", "parent_id")

        env = type("E", (), {"registry": reg})()
        cols = _resolve_o2m_table_fields(
            env,
            "inline.line",
            None,
            inline_columns=["body"],
        )
        self.assertEqual([c["name"] for c in cols], ["body"])


if __name__ == "__main__":
    unittest.main()
