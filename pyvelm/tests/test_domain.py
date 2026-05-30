"""Domain compiler and comodel-unlink cache tests."""
from __future__ import annotations

import unittest
from pathlib import Path

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Char, Environment, Many2many, Registry
from pyvelm.domain import domain_to_sql, normalize_domain
from pyvelm.render import install_module_action
from pyvelm.tests.support.db import DatabaseTestCase, install_modules, reset_database

_EXAMPLE_ROOT = Path(__file__).resolve().parents[2] / "examples" / "modules"
_MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [_EXAMPLE_ROOT]


def _mini_registry():
    reg = Registry()
    with reg.activate():

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            tag_ids = Many2many("test.tag")

    return reg, Partner


class DomainCompileTests(unittest.TestCase):
    def test_m2o_chain_uses_join(self):
        reg = Registry()
        from pyvelm import Many2one

        with reg.activate():

            class Region(BaseModel):
                _name = "test.region"
                name = Char()

            class Country(BaseModel):
                _name = "test.country"
                region_id = Many2one("test.region")

            class Partner(BaseModel):
                _name = "test.partner"
                country_id = Many2one("test.country")

        where, params, joins = domain_to_sql(
            [("country_id.region_id.name", "=", "EU")],
            Partner,
            reg,
        )
        self.assertIn("LEFT JOIN", joins)
        self.assertNotIn("EXISTS", where)
        self.assertEqual(params, ["EU"])

    def test_m2m_path_uses_exists(self):
        reg, Partner = _mini_registry()
        where, params, joins = domain_to_sql(
            [("tag_ids.name", "=", "VIP")],
            Partner,
            reg,
        )
        self.assertIn("EXISTS", where)
        self.assertEqual(joins, "")
        self.assertEqual(params, ["VIP"])

    def test_all_quantifier_wraps_not_exists(self):
        reg, Partner = _mini_registry()
        where, params, _joins = domain_to_sql(
            [("tag_ids.name", "!=", "VIP", {"all": True})],
            Partner,
            reg,
        )
        self.assertIn("NOT (EXISTS", where)
        self.assertEqual(params, ["VIP"])

    def test_all_comparison_uses_inverted_op(self):
        from pyvelm import Integer
        from pyvelm.vellum import Vellum

        reg = Registry()
        with reg.activate():

            class Tag(BaseModel):
                _name = "test.tag_scored"
                score = Integer()

            class PartnerScored(Vellum, BaseModel):
                _name = "test.partner_scored"
                tag_ids = Many2many("test.tag_scored")

        where, params, _ = domain_to_sql(
            [("tag_ids.score", ">", 10, {"all": True})],
            PartnerScored,
            reg,
        )
        self.assertIn("NOT (EXISTS", where)
        self.assertIn("<=", where)
        self.assertEqual(params, [10])

    def test_all_on_simple_field_raises(self):
        reg, Partner = _mini_registry()
        with self.assertRaises(ValueError):
            domain_to_sql(
                [("name", "=", "x", {"all": True})],
                Partner,
                reg,
            )

    def test_or_subleaf_m2m_uses_exists(self):
        reg, Partner = _mini_registry()
        where, params, joins = domain_to_sql(
            [
                (
                    "__or__",
                    "=",
                    [
                        ("tag_ids.name", "ilike", "%vip%"),
                        ("name", "ilike", "%vip%"),
                    ],
                )
            ],
            Partner,
            reg,
        )
        self.assertIn("EXISTS", where)
        self.assertIn(" OR ", where)
        self.assertEqual(len(params), 2)

    def test_polish_or_two_leaves(self):
        reg, Partner = _mini_registry()
        where, params, _joins = domain_to_sql(
            ["|", ("name", "ilike", "%a%"), ("name", "ilike", "%b%")],
            Partner,
            reg,
        )
        self.assertIn(" OR ", where)
        self.assertEqual(params, ["%a%", "%b%"])

    def test_polish_and_or_nested(self):
        reg, Partner = _mini_registry()
        where, params, _joins = domain_to_sql(
            [
                "&",
                ("name", "!=", None),
                "|",
                ("name", "ilike", "%vip%"),
                ("tag_ids.name", "ilike", "%vip%"),
            ],
            Partner,
            reg,
        )
        self.assertIn(" AND ", where)
        self.assertIn(" OR ", where)
        self.assertIn("EXISTS", where)
        self.assertEqual(len(params), 2)

    def test_polish_not(self):
        reg, Partner = _mini_registry()
        where, params, _joins = domain_to_sql(
            ["!", ("name", "=", "blocked")],
            Partner,
            reg,
        )
        self.assertIn("NOT (", where)
        self.assertEqual(params, ["blocked"])

    def test_implicit_and_flat_leaves(self):
        reg, Partner = _mini_registry()
        where, params, _joins = domain_to_sql(
            [("name", "ilike", "%a%"), ("name", "ilike", "%b%")],
            Partner,
            reg,
        )
        self.assertIn(" AND ", where)
        self.assertEqual(params, ["%a%", "%b%"])

    def test_normalize_domain_implicit_and(self):
        norm = normalize_domain([("a", "=", 1), ("b", "=", 2)])
        self.assertEqual(norm, ["&", ("a", "=", 1), ("b", "=", 2)])

    def test_mime_style_or_expansion(self):
        """Same shape as web._accept_mime_domain — prefix | operators."""
        reg, Partner = _mini_registry()
        domain = ["|", ("name", "ilike", "image/%"), ("name", "ilike", "application/%")]
        where, params, _ = domain_to_sql(domain, Partner, reg)
        self.assertIn(" OR ", where)
        self.assertEqual(len(params), 2)


class DomainCacheIntegrationTests(DatabaseTestCase):
    """Cache invalidation tests with bootstrap + partners only."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_database(cls.dsn)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        install_modules(cls.env, _MODULE_ROOTS)
        install_module_action(cls.env, list(_MODULE_ROOTS), "partners")
        cls.Partner = cls.env["res.partner"]
        cls.Country = cls.env["res.country"]
        cls.Tag = cls.env["res.tag"]

    def test_comodel_unlink_clears_many2one_cache(self):
        country = self.Country.create({"name": "CacheUnlink", "code": "CU"})
        partner = self.Partner.create(
            {"name": "CachePartner", "code": "CP1", "country_id": country}
        )
        self.assertEqual(partner.country_id.id, country.id)
        country.unlink()
        p = self.Partner.browse(partner.id)
        self.assertFalse(p.country_id)

    def test_partner_tag_write_clears_tag_partner_ids_cache(self):
        tag = self.Tag.create({"name": "SymCache"})
        partner = self.Partner.create(
            {"name": "SymPartner", "code": "SP1", "tag_ids": [tag]}
        )
        t = self.Tag.browse(tag.id)
        self.assertIn(partner, t.partner_ids)
        partner.write({"tag_ids": []})
        t2 = self.Tag.browse(tag.id)
        self.assertEqual(len(t2.partner_ids), 0)


if __name__ == "__main__":
    unittest.main()
