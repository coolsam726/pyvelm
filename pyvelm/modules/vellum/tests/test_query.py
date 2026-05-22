"""Vellum Slice A tests — require PYVELM_DSN and a writable database."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader
from pyvelm.vellum import Vellum

DSN = os.environ.get("PYVELM_DSN")
HERE = Path(__file__).resolve().parents[4]
DEMO_ROOT = HERE / "examples" / "modules"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [DEMO_ROOT]


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class VellumQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env)
        from vellum_demo.models.note import DemoNote

        cls.DemoNote = DemoNote
        Note = cls.env["vellum.demo.note"]
        Note.search([]).unlink()
        cls.a = Note.create({"title": "Alpha", "score": 10})
        cls.b = Note.create({"title": "Beta", "score": 50})
        cls.c = Note.create({"title": "Gamma", "score": 120})

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_query_where_get_matches_search(self):
        direct = self.env["vellum.demo.note"].search(
            [("score", ">", 40)], order='"id" ASC'
        )
        via_qb = self.env.query("vellum.demo.note").where(
            "score", ">", 40
        ).order_by("id", "asc").get()
        self.assertEqual(set(direct._ids), set(via_qb._ids))

    def test_env_query_uses_registry_class(self):
        """env.query must hit the merged registry class, not a stale import."""
        reg_cls = self.env.registry["vellum.demo.note"]
        qb = self.env.query("vellum.demo.note")
        self.assertIs(qb.model_cls, reg_cls)
        self.assertEqual(
            set(qb.where("score", ">", 40).get()._ids),
            set(self.env["vellum.demo.note"].search([("score", ">", 40)])._ids),
        )

    def test_first_empty_recordset(self):
        empty = (
            self.DemoNote.query(self.env)
            .where("title", "=", "no-such-note")
            .first()
        )
        self.assertFalse(empty)
        self.assertEqual(empty._name, "vellum.demo.note")

    def test_find_and_find_or_fail(self):
        found = self.DemoNote.query(self.env).find(self.a.id)
        self.assertEqual(found._ids, (self.a.id,))
        missing = self.DemoNote.query(self.env).where("score", ">", 200).find(
            self.a.id
        )
        self.assertFalse(missing)
        with self.assertRaises(ValueError):
            self.DemoNote.query(self.env).find_or_fail(999_999)

    def test_pluck_count_exists_paginate(self):
        qb = self.DemoNote.query(self.env).where("score", ">=", 10)
        self.assertEqual(qb.count(), 3)
        self.assertTrue(qb.exists())
        titles = sorted(qb.pluck("title"))
        self.assertEqual(titles, ["Alpha", "Beta", "Gamma"])
        page = qb.order_by("score", "asc").paginate(page=2, per_page=2)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["page"], 2)
        self.assertEqual(len(page["items"]), 1)

    def test_chunk(self):
        chunks = list(
            self.DemoNote.query(self.env).order_by("id", "asc").chunk(2)
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 2)
        self.assertEqual(len(chunks[1]), 1)

    def test_collection_pluck_and_in_memory_where(self):
        all_notes = self.DemoNote.query(self.env).order_by("id", "asc").get()
        hot = all_notes.where("score", ">", 40)
        self.assertEqual([n.title for n in hot], ["Beta", "Gamma"])
        self.assertEqual(all_notes.pluck("title"), ["Alpha", "Beta", "Gamma"])
        self.assertTrue(all_notes.contains(self.a))
        self.assertEqual(all_notes.find(self.b.id)._ids, (self.b.id,))
        self.assertFalse(all_notes.find(999_999))

    def test_where_any(self):
        or_notes = (
            self.DemoNote.query(self.env)
            .where_any(
                ("title", "=", "Alpha"),
                ("title", "=", "Gamma"),
            )
            .get()
        )
        self.assertEqual(set(or_notes._ids), {self.a.id, self.c.id})

    def test_mixin_on_recordset(self):
        self.assertTrue(issubclass(self.DemoNote, Vellum))


if __name__ == "__main__":
    unittest.main()
