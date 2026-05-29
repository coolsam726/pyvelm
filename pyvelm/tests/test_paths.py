"""Unit tests for ``pyvelm.paths`` — the dotted-path parser + hop graph."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Many2many, Many2one, One2many, Registry
from pyvelm.paths import (
    HopEdge,
    Hop,
    M2mHop,
    M2oHop,
    O2mHop,
    parse_path,
)


def _stack():
    """Partner with M2o / O2m / M2m relations for path parsing."""
    reg = Registry()
    with reg.activate():

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Country(BaseModel):
            _name = "test.country"
            name = Char()

        class Line(BaseModel):
            _name = "test.line"
            partner_id = Many2one("test.partner")

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            country_id = Many2one("test.country")
            line_ids = One2many("test.line", "partner_id")
            tag_ids = Many2many("test.tag")

    return reg, Partner


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list[tuple] = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return _FakeResult(self._rows)


class _FakeField:
    def __init__(self, column):
        self.column = column


class _FakeModel:
    def __init__(self, table, fields=None):
        self._table = table
        self._fields = fields or {}


class _FakeEnv:
    def __init__(self, conn, registry):
        self.conn = conn
        self.registry = registry


class HopReverseWalkTests(unittest.TestCase):
    def test_base_hop_reverse_walk_not_implemented(self):
        hop = Hop("test.partner", "x", None, "test.country")
        with self.assertRaises(NotImplementedError):
            hop.reverse_walk(None, [1])

    def test_m2o_empty_ids_short_circuits(self):
        hop = M2oHop("test.partner", "country_id", _FakeField("country_id"), "test.country")
        self.assertEqual(hop.reverse_walk(None, []), [])

    def test_m2o_reverse_walk_sql(self):
        conn = _FakeConn([(1,), (2,)])
        env = _FakeEnv(conn, {"test.partner": _FakeModel("test_partner")})
        hop = M2oHop("test.partner", "country_id", _FakeField("country_id"), "test.country")
        self.assertEqual(hop.reverse_walk(env, [10]), [1, 2])
        self.assertIn("test_partner", conn.calls[0][0])

    def test_o2m_empty_ids_short_circuits(self):
        hop = O2mHop("test.partner", "line_ids", None, "test.line", "partner_id")
        self.assertEqual(hop.reverse_walk(None, []), [])

    def test_o2m_reverse_walk_sql(self):
        conn = _FakeConn([(5,)])
        line = _FakeModel("test_line", {"partner_id": _FakeField("partner_id")})
        env = _FakeEnv(conn, {"test.line": line})
        hop = O2mHop("test.partner", "line_ids", None, "test.line", "partner_id")
        self.assertEqual(hop.reverse_walk(env, [1, 2]), [5])
        self.assertIn("test_line", conn.calls[0][0])

    def test_m2m_empty_ids_short_circuits(self):
        hop = M2mHop("test.partner", "tag_ids", None, "test.tag", "rel", "p", "t")
        self.assertEqual(hop.reverse_walk(None, []), [])

    def test_m2m_reverse_walk_sql(self):
        conn = _FakeConn([(7,), (8,)])
        env = _FakeEnv(conn, {})
        hop = M2mHop("test.partner", "tag_ids", None, "test.tag", "rel_tbl", "pid", "tid")
        self.assertEqual(hop.reverse_walk(env, [3]), [7, 8])
        self.assertIn("rel_tbl", conn.calls[0][0])


class HopEdgeTests(unittest.TestCase):
    def test_find_source_ids_short_circuits_on_empty(self):
        hop = M2oHop("test.partner", "x", _FakeField("x"), "test.country")
        edge = HopEdge(
            listen_at=("test.country", "name"),
            to_source=lambda env, ids: [],   # produces empty → loop bails
            hops_to_walk=[hop],
        )
        self.assertEqual(edge.find_source_ids(None, [1, 2]), [])

    def test_find_source_ids_walks_hops(self):
        conn = _FakeConn([(99,)])
        env = _FakeEnv(conn, {"test.partner": _FakeModel("test_partner")})
        hop = M2oHop("test.partner", "x", _FakeField("x"), "test.country")
        edge = HopEdge(
            listen_at=("test.country", "name"),
            to_source=lambda e, ids: list(ids),
            hops_to_walk=[hop],
        )
        self.assertEqual(edge.find_source_ids(env, [1]), [99])


class ParsePathTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _stack()

    def test_m2o_leaf(self):
        p = parse_path(self.Partner, "country_id.name", self.reg)
        self.assertTrue(p.is_m2o_only())
        self.assertEqual(p.leaf_model, "test.country")
        self.assertEqual(p.leaf_attr, "name")
        self.assertEqual(p.reads()[-1], ("test.country", "name"))

    def test_id_leaf(self):
        p = parse_path(self.Partner, "country_id.id", self.reg)
        self.assertEqual(p.leaf_attr, "id")
        self.assertEqual(p.leaf_model, "test.country")

    def test_scalar_leaf_no_hops(self):
        p = parse_path(self.Partner, "name", self.reg)
        self.assertEqual(p.hops, [])
        self.assertEqual(p.leaf_attr, "name")

    def test_o2m_hop_then_leaf(self):
        p = parse_path(self.Partner, "line_ids.partner_id", self.reg)
        self.assertIsInstance(p.hops[0], O2mHop)
        self.assertFalse(p.is_m2o_only())

    def test_m2m_hop_then_leaf(self):
        p = parse_path(self.Partner, "tag_ids.name", self.reg)
        self.assertIsInstance(p.hops[0], M2mHop)

    def test_empty_token_rejected(self):
        with self.assertRaises(ValueError):
            parse_path(self.Partner, "country_id..name", self.reg)

    def test_id_must_be_leaf(self):
        with self.assertRaises(ValueError):
            parse_path(self.Partner, "id.name", self.reg)

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            parse_path(self.Partner, "nope", self.reg)

    def test_non_relational_non_leaf_rejected(self):
        with self.assertRaises(ValueError):
            parse_path(self.Partner, "name.foo", self.reg)


class PathEdgesTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner = _stack()

    def test_m2o_edges(self):
        p = parse_path(self.Partner, "country_id.name", self.reg)
        edges = p.edges()
        # one per hop + one leaf edge
        self.assertEqual(len(edges), 2)
        self.assertEqual(edges[0].listen_at, ("test.partner", "country_id"))
        self.assertEqual(edges[-1].listen_at, ("test.country", "name"))
        # The M2o/leaf edges use the identity ``to_source``.
        self.assertEqual(edges[0].to_source(None, [1, 2]), [1, 2])

    def test_o2m_edge_listens_on_inverse(self):
        p = parse_path(self.Partner, "line_ids.partner_id", self.reg)
        edges = p.edges()
        self.assertEqual(edges[0].listen_at, ("test.line", "partner_id"))

    def test_m2m_edge_listens_on_source(self):
        p = parse_path(self.Partner, "tag_ids.name", self.reg)
        edges = p.edges()
        self.assertEqual(edges[0].listen_at, ("test.partner", "tag_ids"))


if __name__ == "__main__":
    unittest.main()
