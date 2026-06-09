"""Tests for ``pyvelm.models.Model`` (Odoo-style model base)."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Registry, models


class ModelsModuleTests(unittest.TestCase):
    def test_model_subclasses_basemodel(self) -> None:
        self.assertTrue(issubclass(models.Model, BaseModel))

    def test_inherit_via_models_model(self) -> None:
        reg = Registry()
        with reg.activate():
            class Root(models.Model):
                _name = "test.models.root"
                name = Char()

        with reg.activate():
            class Ext(models.Model):
                _inherit = "test.models.root"
                note = Char()

        cls = reg["test.models.root"]
        self.assertIs(cls, Ext)
        self.assertIn("note", cls._fields)
        self.assertIn("name", cls._fields)


if __name__ == "__main__":
    unittest.main()
