"""One2many/Many2many cache + eager-load tests (core + Vellum)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.fields import _collection_ids_from_cache

DSN = os.environ.get("PYVELM_DSN")
HERE = Path(__file__).resolve().parents[4]
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class O2mCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env)
        cls.Partner = cls.env["res.partner"]

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_one2many_populates_and_reuses_cache(self):
        parent = self.Partner.create({"name": "CacheParent"})
        child = self.Partner.create({"name": "CacheChild", "parent_id": parent})
        self.assertTrue(child.parent_id == parent)
        p = self.Partner.browse(parent.id)
        self.assertIsNone(
            _collection_ids_from_cache(self.env.cache, "res.partner", parent.id, "child_ids")
        )
        first = p.child_ids
        self.assertEqual(first._ids, (child.id,))
        cached = _collection_ids_from_cache(
            self.env.cache, "res.partner", parent.id, "child_ids"
        )
        self.assertEqual(cached, (child.id,))
        with mock.patch.object(
            self.env.conn, "execute", wraps=self.env.conn.execute
        ) as execute:
            second = p.child_ids
            self.assertEqual(second._ids, (child.id,))
            self.assertEqual(execute.call_count, 0)

    def test_parent_id_write_invalidates_child_ids_cache(self):
        parent_a = self.Partner.create({"name": "ParentA"})
        parent_b = self.Partner.create({"name": "ParentB"})
        child = self.Partner.create({"name": "Mover", "parent_id": parent_a})
        _ = parent_a.child_ids
        child.write({"parent_id": parent_b})
        self.assertIsNone(
            _collection_ids_from_cache(
                self.env.cache, "res.partner", parent_a.id, "child_ids"
            )
        )
        self.assertEqual(parent_b.child_ids._ids, (child.id,))

    def test_env_query_with_eager_child_ids(self):
        parent = self.Partner.create({"name": "EagerParent"})
        c1 = self.Partner.create({"name": "E1", "parent_id": parent})
        c2 = self.Partner.create({"name": "E2", "parent_id": parent})
        parents = self.env.query("res.partner").where(
            "id", "=", parent.id
        ).with_("child_ids").get()
        self.assertEqual(len(parents), 1)
        with mock.patch.object(
            self.env.conn, "execute", wraps=self.env.conn.execute
        ) as execute:
            kids = parents.child_ids
            self.assertEqual(set(kids._ids), {c1.id, c2.id})
            self.assertEqual(execute.call_count, 0)


if __name__ == "__main__":
    unittest.main()
