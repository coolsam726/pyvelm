"""Tests for ``pyvelm.mass_assignment``."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Registry
from pyvelm.mass_assignment import filter_mass_assignment, validate_mass_assignment_config


class _Policy:
    _name = "test.policy"


class MassAssignmentTests(unittest.TestCase):
    def test_fillable_whitelists_keys(self):
        class Item(_Policy):
            _fillable = ["name"]

        out = filter_mass_assignment(Item, {"name": "a", "secret": "x"})
        self.assertEqual(out, {"name": "a"})

    def test_guarded_drops_listed_keys(self):
        class Item(_Policy):
            _guarded = ["id"]

        out = filter_mass_assignment(Item, {"id": 9, "name": "a"})
        self.assertEqual(out, {"name": "a"})

    def test_guarded_star_blocks_all(self):
        class Item(_Policy):
            _guarded = ["*"]

        out = filter_mass_assignment(Item, {"name": "a"})
        self.assertEqual(out, {})

    def test_fillable_strict_raises(self):
        class Item(_Policy):
            _fillable = ["name"]
            _strict_fillable = True

        with self.assertRaises(ValueError):
            filter_mass_assignment(Item, {"name": "a", "bad": 1})

    def test_fillable_and_guarded_mutually_exclusive(self):
        class Bad(_Policy):
            _fillable = ["name"]
            _guarded = ["id"]

        with self.assertRaises(TypeError):
            validate_mass_assignment_config(Bad)

        reg = Registry()
        with reg.activate():
            with self.assertRaises(TypeError):

                class Registered(BaseModel):
                    _name = "test.bad_policy"
                    _fillable = ["name"]
                    _guarded = ["id"]
                    name = Char()

    def test_registry_validates_on_register(self):
        reg = Registry()
        with reg.activate():

            class Good(BaseModel):
                _name = "test.reg_guarded"
                _guarded = ["id"]
                name = Char()

            reg.register(Good)
        self.assertIn("test.reg_guarded", reg)


if __name__ == "__main__":
    unittest.main()
