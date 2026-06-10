"""Fluent ORM field builders (``Char().required()``)."""
from __future__ import annotations

import unittest

from pyvelm import (
    BaseModel,
    Char,
    Code,
    Integer,
    Many2many,
    Many2one,
    Monetary,
    One2many,
    Registry,
    Text,
    models,
)
from pyvelm.field_builders import (
    OrmFieldBuilder,
    field_new,
    materialize_field,
    materialize_namespace_fields,
)


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

    def test_builder_scalar_and_relation_chains(self):
        built = materialize_field(
            Char()
            .column("partner_code")
            .compute("_compute_code")
            .store(False)
            .related("parent_id.code")
            .readonly()
            .size(64)
            .choices(["a", "b"])
        )
        self.assertEqual(built._column_override, "partner_code")
        self.assertEqual(built.compute, "_compute_code")
        self.assertFalse(built.is_stored)
        self.assertEqual(built.related, "parent_id.code")
        self.assertTrue(built.readonly)
        self.assertEqual(built.size, 64)
        self.assertEqual(built.choices, [("a", "a"), ("b", "b")])

        code = materialize_field(Code().language("python"))
        self.assertEqual(code.language, "python")

        money = materialize_field(Monetary().currency_field("currency_id"))
        self.assertEqual(money.currency_field, "currency_id")

        m2o = materialize_field(Many2one().comodel("res.partner").ondelete("CASCADE"))
        self.assertEqual(m2o.comodel_name, "res.partner")
        self.assertEqual(m2o.ondelete, "CASCADE")

        bare_inverse = One2many().inverse("partner_id")
        self.assertEqual(bare_inverse._kwargs["inverse_name"], "partner_id")

        o2m = materialize_field(
            One2many("res.partner", "partner_id").form_view(
                ("partners", "partner.form")
            )
        )
        self.assertEqual(o2m.comodel_name, "res.partner")
        self.assertEqual(o2m.inverse_name, "partner_id")
        self.assertEqual(o2m.form_view, ("partners", "partner.form"))

        m2m = materialize_field(
            Many2many("res.tags")
            .relation("partner_tag_rel")
            .column1("partner_id")
            .column2("tag_id")
        )
        self.assertEqual(m2m._relation_override, "partner_tag_rel")
        self.assertEqual(m2m._column1_override, "partner_id")
        self.assertEqual(m2m._column2_override, "tag_id")

    def test_materialize_field_passthrough(self):
        plain = Char.bare(required=True)
        self.assertIs(materialize_field(plain), plain)

    def test_materialize_namespace_fields(self):
        builder = Text().string("Notes")
        namespace = {"notes": builder, "keep": 1}
        materialize_namespace_fields(namespace)
        self.assertIsInstance(namespace["notes"], Text)
        self.assertEqual(namespace["notes"].string, "Notes")
        self.assertEqual(namespace["keep"], 1)

    def test_field_new_kwargs_and_builder(self):
        direct = field_new(Char, required=True)
        self.assertIsInstance(direct, Char)
        builder = field_new(Char)
        self.assertIsInstance(builder, OrmFieldBuilder)
        with_args = field_new(Many2one, "res.country")
        self.assertIsInstance(with_args, OrmFieldBuilder)
        self.assertEqual(with_args._args, ("res.country",))


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
