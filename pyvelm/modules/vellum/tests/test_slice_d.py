"""Vellum Slice D — mass assignment and soft deletes."""
from __future__ import annotations

import unittest
from pathlib import Path

from pyvelm.tests.support.db import DatabaseTestCase
from pyvelm import BUILTIN_MODULE_ROOTS, BaseModel, Char, Environment, Registry, loader
from pyvelm.vellum import SoftDeletes, Vellum
from pyvelm.vellum.fillable import filter_mass_assignment
from pyvelm.vellum.timestamps import apply_timestamp_vals

HERE = Path(__file__).resolve().parents[4]
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "examples" / "modules"]


class VellumSliceDTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reg = Registry()
        cls.env = Environment(cls.conn, registry=cls.reg, uid=1)
        loader.load_and_install(MODULE_ROOTS, cls.env, install_all=True)
        cls.env.conn.execute(
            'ALTER TABLE "vellum_demo_soft_note" '
            'ADD COLUMN IF NOT EXISTS "deleted_at" timestamp'
        )

    def test_guarded_drops_id_on_create(self):
        Note = self.env["vellum.demo.note"]
        note = Note.create(
            {"id": 99999, "title": "ok", "body": "b", "score": 1}
        )
        self.assertNotEqual(note.id, 99999)
        self.assertEqual(note.title, "ok")
        self.assertIsNotNone(note.created_at)
        self.assertIsNotNone(note.updated_at)

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
        note.fill({"title": "after", "id": 99999})
        self.assertEqual(note.title, "after")
        self.assertNotEqual(note.id, 99999)

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


class MassAssignmentPolicyTests(unittest.TestCase):
    def test_guarded_star_blocks_all(self):
        class M:
            _name = "test.m"
            _guarded = ["*"]

        self.assertEqual(filter_mass_assignment(M, {"a": 1, "b": 2}), {})

    def test_guarded_allows_unlisted_keys(self):
        class M:
            _name = "test.m"
            _guarded = ["id"]

        self.assertEqual(
            filter_mass_assignment(M, {"id": 1, "title": "x"}),
            {"title": "x"},
        )

    def test_vellum_defaults_to_guard_id(self):
        reg = Registry()
        with reg.activate():

            class Post(Vellum, BaseModel):
                _name = "test.post"
                title = Char()

        self.assertEqual(getattr(Post, "_guarded", None), ["id", "created_at", "updated_at"])
        self.assertIn("created_at", Post._fields)
        self.assertIn("updated_at", Post._fields)
        self.assertIsNone(getattr(Post, "_fillable", None))
        self.assertEqual(
            filter_mass_assignment(Post, {"id": 9, "title": "hi", "created_at": "x"}),
            {"title": "hi"},
        )

    def test_timestamps_disabled(self):
        reg = Registry()
        with reg.activate():

            class Legacy(Vellum, BaseModel):
                _name = "test.legacy"
                _timestamps = False
                title = Char()

        self.assertEqual(getattr(Legacy, "_guarded", None), ["id"])
        self.assertNotIn("created_at", Legacy._fields)

    def test_apply_timestamp_vals_on_create(self):
        reg = Registry()
        with reg.activate():

            class Post(Vellum, BaseModel):
                _name = "test.post2"
                title = Char()

        vals = apply_timestamp_vals(Post, {"title": "a"}, updating=False)
        self.assertIn("created_at", vals)
        self.assertIn("updated_at", vals)
        self.assertEqual(vals["created_at"], vals["updated_at"])

    def test_apply_timestamp_vals_on_write(self):
        reg = Registry()
        with reg.activate():

            class Post(Vellum, BaseModel):
                _name = "test.post3"
                title = Char()

        vals = apply_timestamp_vals(Post, {"title": "a"}, updating=True)
        self.assertNotIn("created_at", vals)
        self.assertIn("updated_at", vals)

    def test_fillable_still_whitelists(self):
        class M:
            _name = "test.m"
            _fillable = ["title"]

        self.assertEqual(
            filter_mass_assignment(M, {"title": "a", "body": "b"}),
            {"title": "a"},
        )


if __name__ == "__main__":
    unittest.main()
