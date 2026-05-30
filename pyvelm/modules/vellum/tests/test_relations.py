"""Vellum Slice B — relations + with_count."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Environment, One2many, Registry, loader
from pyvelm.vellum import Vellum

DSN = os.environ.get("PYVELM_DSN")
HERE = Path(__file__).resolve().parents[4]
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class VellumRelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env, install_all=True)
        Note = cls.env["vellum.demo.note"]
        Comment = cls.env["vellum.demo.comment"]
        Comment.search([]).unlink()
        Note.search([]).unlink()
        cls.note = Note.create({"title": "RelNote"})
        cls.c1 = Comment.create({"note_id": cls.note, "body": "a"})
        cls.c2 = Comment.create({"note_id": cls.note, "body": "b"})

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_has_many_on_instance(self):
        note = self.env["vellum.demo.note"].browse(self.note.id)
        comments = note.has_many("vellum.demo.comment", "note_id").order_by(
            "id", "asc"
        ).get()
        self.assertEqual(comments._ids, (self.c1.id, self.c2.id))

    def test_belongs_to_on_comment(self):
        comment = self.env["vellum.demo.comment"].browse(self.c1.id)
        note = comment.belongs_to("vellum.demo.note", "note_id").get()
        self.assertEqual(note._ids, (self.note.id,))

    def test_env_query_with_count(self):
        notes = (
            self.env.query("vellum.demo.note")
            .where("id", "=", self.note.id)
            .with_count("comment_ids")
            .get()
        )
        self.assertEqual(notes.count_of("comment_ids"), 2)

    def test_field_method_name_collision_rejected(self):
        reg = Registry()
        with reg.activate():
            with self.assertRaises(TypeError):

                class BadNote(Vellum, BaseModel):
                    _name = "vellum.demo.bad"

                    bad_ids = One2many("vellum.demo.comment", "note_id")

                    def bad_ids(self):
                        return self.has_many("vellum.demo.comment", "note_id")


if __name__ == "__main__":
    unittest.main()
