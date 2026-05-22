"""Domain compiler and comodel-unlink cache tests."""
from __future__ import annotations

import os
import unittest

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Char, Environment, Many2many, Registry, loader
from pyvelm.domain import domain_to_sql

DSN = os.environ.get("PYVELM_DSN")

try:
    import psycopg as _psycopg
except ImportError:
    _psycopg = None


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


@unittest.skipUnless(DSN and _psycopg, "PYVELM_DSN / psycopg not available")
class DomainCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.conn = _psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        roots = BUILTIN_MODULE_ROOTS + [
            Path(__file__).resolve().parents[2] / "examples" / "modules"
        ]
        loader.load_and_install(roots, cls.env)
        cls.Partner = cls.env["res.partner"]
        cls.Country = cls.env["res.country"]

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_comodel_unlink_clears_many2one_cache(self):
        country = self.Country.create({"name": "CacheUnlink", "code": "CU"})
        partner = self.Partner.create({"name": "CachePartner", "country_id": country})
        self.assertEqual(partner.country_id.id, country.id)
        country.unlink()
        p = self.Partner.browse(partner.id)
        self.assertFalse(p.country_id)


@unittest.skipUnless(DSN and _psycopg, "PYVELM_DSN / psycopg not available")
class M2mSymmetricCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path

        cls.conn = _psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        roots = BUILTIN_MODULE_ROOTS + [
            Path(__file__).resolve().parents[2] / "examples" / "modules"
        ]
        loader.load_and_install(roots, cls.env)
        cls.Partner = cls.env["res.partner"]
        cls.Tag = cls.env["res.tag"]

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_partner_tag_write_clears_tag_partner_ids_cache(self):
        tag = self.Tag.create({"name": "SymCache"})
        partner = self.Partner.create({"name": "SymPartner", "tag_ids": [tag]})
        t = self.Tag.browse(tag.id)
        self.assertIn(partner, t.partner_ids)
        partner.write({"tag_ids": []})
        t2 = self.Tag.browse(tag.id)
        self.assertEqual(len(t2.partner_ids), 0)


if __name__ == "__main__":
    unittest.main()
