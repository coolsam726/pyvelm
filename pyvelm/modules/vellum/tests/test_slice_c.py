"""Vellum Slice C — scopes, accessors, mutators, events."""
from __future__ import annotations

import unittest
from pathlib import Path

from pyvelm.tests.support.db import DatabaseTestCase
from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

HERE = Path(__file__).resolve().parents[4]
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


class VellumSliceCTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env, install_all=True)
        Note = cls.env["vellum.demo.note"]
        Comment = cls.env["vellum.demo.comment"]
        Comment.search([]).unlink()
        Note.search([]).unlink()
        cls.env.registry["vellum.demo.note"]._created_log.clear()

    def test_scope_on_env_query(self):
        Note = self.env["vellum.demo.note"]
        low = Note.create({"title": "low", "score": 10})
        high = Note.create({"title": "high", "score": 90})
        found = self.env.query("vellum.demo.note").high_score().get()
        self.assertIn(high.id, found._ids)
        self.assertNotIn(low.id, found._ids)

    def test_accessor_title_upper(self):
        note = self.env["vellum.demo.note"].create({"title": "hello", "score": 1})
        note.ensure_one()
        self.assertEqual(note.title_upper, "HELLO")

    def test_mutator_strips_title_on_create(self):
        note = self.env["vellum.demo.note"].create(
            {"title": "  padded  ", "score": 1}
        )
        self.assertEqual(note.title, "padded")

    def test_on_created_event(self):
        self.env["vellum.demo.note"].create({"title": "EventNote", "score": 1})
        log = self.env.registry["vellum.demo.note"]._created_log
        self.assertIn("EventNote", log)

    def test_mutator_on_write(self):
        note = self.env["vellum.demo.note"].create({"title": "x", "score": 1})
        note.write({"title": "  updated  "})
        self.assertEqual(note.title, "updated")


if __name__ == "__main__":
    unittest.main()
