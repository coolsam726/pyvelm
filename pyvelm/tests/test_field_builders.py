"""Fluent ORM field builders (``Char().required()``)."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Integer, Many2one, One2many, Registry, models
from pyvelm.field_builders import OrmFieldBuilder, materialize_field


class OrmFieldBuilderUnitTests(unittest.TestCase):
    def test_materialize_builds_field(self):
        built = materialize_field(Char().required().string("Title"))
        self.assertIsInstance(built, Char)
        self.assertTrue(built.required)
        self.assertEqual(built.string, "Title")

    def test_constructor_kwargs_unchanged(self):
        f = Char(required=True, string="Name")
        self.assertIsInstance(f, Char)
        self.assertTrue(f.required)

    def test_many2one_fluent_chain(self):
        f = materialize_field(
            Many2one("res.country").required().ondelete("CASCADE")
        )
        self.assertEqual(f.comodel_name, "res.country")
        self.assertTrue(f.required)
        self.assertEqual(f.ondelete, "CASCADE")

    def test_one2many_fluent_inverse(self):
        f = materialize_field(
            One2many("res.partner").inverse("parent_id").list_view("child.list")
        )
        self.assertEqual(f.comodel_name, "res.partner")
        self.assertEqual(f.inverse_name, "parent_id")
        self.assertEqual(f.list_view, "child.list")


class FluentModelDeclarationTests(unittest.TestCase):
    def test_model_class_materializes_builders(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.fluent.country"
                code = Char().required()

            class Partner(models.Model):
                _name = "test.fluent.partner"
                name = Char().required().string("Name").tracking()
                age = Integer().default(0)
                country_id = Many2one("test.fluent.country").ondelete("SET NULL")

        self.assertTrue(Partner._fields["name"].required)
        self.assertTrue(Partner._fields["name"].tracking)
        self.assertEqual(Partner._fields["age"].default, 0)
        self.assertEqual(
            Partner._fields["country_id"].comodel_name,
            "test.fluent.country",
        )
        self.assertTrue(Country._fields["code"].required)

    def test_empty_char_returns_builder_not_field(self):
        b = Char()
        self.assertIsInstance(b, OrmFieldBuilder)
        self.assertNotIsInstance(b, Char)
