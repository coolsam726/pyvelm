"""Additional unit tests for ``pyvelm.domain``."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Integer, Many2one, One2many, Registry
from pyvelm.domain import (
    domain_to_sql,
    expand_or_groups,
    is_domain_leaf,
    iter_domain_leaves,
    normalize_domain,
)


def _partner_line_registry():
    reg = Registry()
    with reg.activate():
        from pyvelm import Many2many

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Line(BaseModel):
            _name = "test.line"
            partner_id = Many2one("test.partner")
            qty = Integer()

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            line_ids = One2many("test.line", "partner_id")
            tag_ids = Many2many("test.tag")

    return reg, Partner


class DomainHelperTests(unittest.TestCase):
    def test_is_domain_leaf(self):
        self.assertTrue(is_domain_leaf(("name", "=", "x")))
        self.assertFalse(is_domain_leaf("&"))
        self.assertFalse(is_domain_leaf("not-a-leaf"))

    def test_expand_or_groups_empty_and_single(self):
        self.assertEqual(expand_or_groups([("__or__", "=", [])]), [])
        self.assertEqual(
            expand_or_groups([("__or__", "=", [("name", "=", "a")])]),
            [("name", "=", "a")],
        )
        out = expand_or_groups([
            ("__or__", "=", [("a", "=", 1), ("b", "=", 2)]),
        ])
        self.assertEqual(out, ["|", ("a", "=", 1), ("b", "=", 2)])

    def test_normalize_domain_invalid(self):
        with self.assertRaises(ValueError):
            normalize_domain(["&"])
        with self.assertRaises(ValueError):
            normalize_domain(["not-an-operator"])

    def test_iter_domain_leaves_yields_all(self):
        domain = ["&", ("name", "=", "a"), "|", ("qty", ">", 1), ("qty", "<", 9)]
        leaves = list(iter_domain_leaves(domain))
        self.assertEqual(len(leaves), 3)

    def test_empty_domain_is_true(self):
        reg, Partner = _partner_line_registry()
        where, params, joins = domain_to_sql([], Partner, reg)
        self.assertEqual(where, "TRUE")
        self.assertEqual(params, [])
        self.assertEqual(joins, "")


class DomainOperatorTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _partner_line_registry()

    def test_null_equality_on_simple_field(self):
        where, params, _ = domain_to_sql([("name", "=", None)], self.Partner, self.reg)
        self.assertIn("IS NULL", where)
        self.assertEqual(params, [])
        where2, _, _ = domain_to_sql([("name", "!=", None)], self.Partner, self.reg)
        self.assertIn("IS NOT NULL", where2)

    def test_in_empty_is_false(self):
        where, params, _ = domain_to_sql([("name", "in", [])], self.Partner, self.reg)
        self.assertEqual(where, "FALSE")
        self.assertEqual(params, [])

    def test_not_in_empty_is_true(self):
        where, params, _ = domain_to_sql(
            [("name", "not in", [])], self.Partner, self.reg
        )
        self.assertEqual(where, "TRUE")

    def test_like_and_ilike(self):
        where, params, _ = domain_to_sql(
            [("name", "like", "A%")], self.Partner, self.reg
        )
        self.assertIn("LIKE", where)
        where2, params2, _ = domain_to_sql(
            [("name", "ilike", "%vip%")], self.Partner, self.reg
        )
        self.assertIn("ILIKE", where2)
        self.assertEqual(params2, ["%vip%"])

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            domain_to_sql([("missing", "=", 1)], self.Partner, self.reg)

    def test_leaf_opts_must_be_dict(self):
        with self.assertRaises(ValueError):
            domain_to_sql([("name", "=", "x", "bad")], self.Partner, self.reg)


class DomainPathTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _partner_line_registry()

    def test_o2m_path_uses_exists(self):
        where, params, joins = domain_to_sql(
            [("line_ids.qty", ">", 5)], self.Partner, self.reg
        )
        self.assertIn("EXISTS", where)
        self.assertEqual(joins, "")
        self.assertEqual(params, [5])

    def test_m2m_universal_ilike(self):
        where, params, _ = domain_to_sql(
            [("tag_ids.name", "ilike", "%x%", {"all": True})],
            self.Partner,
            self.reg,
        )
        self.assertIn("NOT (EXISTS", where)
        self.assertIn("NOT ILIKE", where)

    def test_exists_empty_in_universal(self):
        where, params, _ = domain_to_sql(
            [("tag_ids.name", "in", [], {"all": True})],
            self.Partner,
            self.reg,
        )
        self.assertEqual(where, "TRUE")
        self.assertEqual(params, [])

    def test_exists_empty_not_in_non_universal(self):
        where, params, _ = domain_to_sql(
            [("tag_ids.name", "not in", [])], self.Partner, self.reg
        )
        self.assertEqual(where, "TRUE")
        self.assertEqual(params, [])

    def test_shared_join_list_mode(self):
        joins: list[str] = []
        aliases: dict = {}
        counter = [0]
        where, params, ret_joins = domain_to_sql(
            [("name", "=", "Acme")],
            self.Partner,
            self.reg,
            joins=joins,
            join_aliases=aliases,
            join_counter=counter,
        )
        self.assertEqual(ret_joins, "")
        self.assertIn("Acme", params)
        self.assertIn('"test_partner"', where)


if __name__ == "__main__":
    unittest.main()
