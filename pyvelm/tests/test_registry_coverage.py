"""Unit tests for ``pyvelm.registry`` helpers not covered by integration tests."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Registry
from pyvelm.registry import active_registry


class RegistryHelperTests(unittest.TestCase):
    def test_active_registry_requires_context(self):
        with self.assertRaises(RuntimeError):
            active_registry()

    def test_registry_iteration_and_items(self):
        reg = Registry()
        with reg.activate():

            class Alpha(BaseModel):
                _name = "test.alpha"
                label = Char()

            class Beta(BaseModel):
                _name = "test.beta"
                label = Char()

            reg.register(Alpha, module_name="mod_a")
            reg.register(Beta, module_name="mod_b")

        self.assertIn("test.alpha", reg)
        self.assertEqual(len(list(reg)), 2)
        names = {name for name, _cls in reg.items()}
        self.assertEqual(names, {"test.alpha", "test.beta"})
        self.assertEqual(reg.models_of("mod_a"), [Alpha])

    def test_finalize_vellum_import_error_is_ignored(self):
        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "test.plain"

        with patch.dict("sys.modules", {"pyvelm.vellum.mixin": None}):
            reg.register(Plain)
        self.assertIn("test.plain", reg)

    def test_reset_db_drops_m2m_and_reinits(self):
        from pyvelm.fields import Many2many

        reg = Registry()
        with reg.activate():

            class Left(BaseModel):
                _name = "test.left"
                _table = "test_left"
                tags = Many2many("test.right")

            class Right(BaseModel):
                _name = "test.right"
                _table = "test_right"

        conn = MagicMock()
        with patch.object(Left, "_drop_table"), patch.object(
            Right, "_drop_table"
        ), patch.object(reg, "init_db") as init_db:
            reg.reset_db(conn)
        executed = [str(c.args[0]) for c in conn.execute.call_args_list]
        self.assertTrue(any("DROP TABLE" in sql for sql in executed))
        init_db.assert_called_once_with(conn)


if __name__ == "__main__":
    unittest.main()
