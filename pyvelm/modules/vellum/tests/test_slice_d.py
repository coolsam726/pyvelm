"""Vellum Slice D — mass assignment and soft deletes."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

import psycopg

from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Environment, Registry, loader
from pyvelm.vellum import SoftDeletes, Vellum

DSN = os.environ.get("PYVELM_DSN")
HERE = Path(__file__).resolve().parents[4]
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


@unittest.skipUnless(DSN, "PYVELM_DSN not set")
class VellumSliceDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg.connect(DSN, autocommit=True)
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env)
        cls.env.conn.execute(
            'ALTER TABLE "vellum_demo_soft_note" '
            'ADD COLUMN IF NOT EXISTS "deleted_at" timestamp'
        )

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_fillable_drops_unknown_keys(self):
        Note = self.env["vellum.demo.note"]
        note = Note.create(
            {"title": "ok", "body": "b", "score": 1, "secret": "nope"}
        )
        self.assertEqual(note.title, "ok")
        self.assertFalse(hasattr(note, "secret"))

    def test_fillable_strict_raises(self):
        Cls = self.env.registry["vellum.demo.note"]
        Cls._strict_fillable = True
        try:
            with self.assertRaises(ValueError):
                Cls(self.env, ()).create({"title": "x", "forbidden": True})
        finally:
            Cls._strict_fillable = False

    def test_fill_method(self):
        note = self.env["vellum.demo.note"].create(
            {"title": "before", "score": 1}
        )
        note.fill({"title": "after", "ignored": True})
        self.assertEqual(note.title, "after")

    def test_soft_delete_hide_and_restore(self):
        Soft = self.env["vellum.demo.soft_note"]
        Soft.search([]).unlink()
        row = Soft.create({"title": "keep"})
        row.delete()
        visible = self.env.query("vellum.demo.soft_note").get()
        self.assertFalse(visible)
        all_rows = self.env.query("vellum.demo.soft_note").with_trashed().get()
        self.assertEqual(all_rows._ids, (row.id,))
        only = self.env.query("vellum.demo.soft_note").only_trashed().get()
        self.assertEqual(only._ids, (row.id,))
        row.restore()
        again = self.env.query("vellum.demo.soft_note").get()
        self.assertEqual(again._ids, (row.id,))

    def test_force_delete(self):
        Soft = self.env["vellum.demo.soft_note"]
        leftover = self.env.query("vellum.demo.soft_note").with_trashed().get()
        if leftover:
            leftover.force_delete()
        row = Soft.create({"title": "gone"})
        rid = row.id
        row.delete()
        row.force_delete()
        self.assertFalse(
            self.env.query("vellum.demo.soft_note")
            .with_trashed()
            .where("id", "=", rid)
            .exists()
        )

    def test_fillable_guarded_mutually_exclusive(self):
        reg = Registry()
        with reg.activate():
            with self.assertRaises(TypeError):

                class Bad(Vellum, BaseModel):
                    _name = "vellum.demo.bad_fill"
                    _fillable = ["a"]
                    _guarded = ["b"]


if __name__ == "__main__":
    unittest.main()
