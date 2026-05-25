"""Framework-level automatic timestamps on BaseModel."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Registry
from pyvelm.timestamps import apply_timestamp_vals, uses_timestamps


class TimestampModelTests(unittest.TestCase):
    def test_injected_on_basemodel_by_default(self):
        reg = Registry()
        with reg.activate():

            class Demo(BaseModel):
                _name = "test.demo"
                title = Char()

        self.assertIn("created_at", Demo._fields)
        self.assertIn("updated_at", Demo._fields)
        self.assertTrue(Demo._fields["created_at"].readonly)
        self.assertTrue(uses_timestamps(Demo))

    def test_opt_out(self):
        reg = Registry()
        with reg.activate():

            class Legacy(BaseModel):
                _name = "test.legacy"
                _timestamps = False
                title = Char()

        self.assertNotIn("created_at", Legacy._fields)

    def test_apply_timestamp_vals_on_create(self):
        reg = Registry()
        with reg.activate():

            class Note(BaseModel):
                _name = "test.note"
                body = Char()

        vals = apply_timestamp_vals(Note, {"body": "hi"}, updating=False)
        self.assertIn("created_at", vals)
        self.assertIn("updated_at", vals)
        self.assertEqual(vals["created_at"], vals["updated_at"])

    def test_apply_timestamp_vals_on_write(self):
        reg = Registry()
        with reg.activate():

            class Post(BaseModel):
                _name = "test.post"
                title = Char()

        vals = apply_timestamp_vals(Post, {"title": "a"}, updating=True)
        self.assertNotIn("created_at", vals)
        self.assertIn("updated_at", vals)

