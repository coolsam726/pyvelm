"""Tests for Odoo-style ``_inherit`` super chaining."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Registry, depends, models
from pyvelm.vellum.mixin import Vellum


class _FakeCache:
    def set(self, *args, **kwargs) -> None:
        pass

    def invalidate(self, *args, **kwargs) -> None:
        pass

    def contains(self, *args, **kwargs) -> bool:
        return True

    def get(self, *args, **kwargs):
        return None


class _FakeEnv:
    def __init__(self, registry: Registry) -> None:
        self.conn = None
        self.registry = registry
        self.uid = 1
        self.company_id = None
        self.cache = _FakeCache()

    def check_access(self, *args, **kwargs) -> None:
        pass

    def notify_changed(self, *args, **kwargs) -> None:
        pass


def _noop_write(self_, vals) -> None:
    InheritSuperChainTests.calls.append("basemodel_write")


def _noop_create(self_, vals):
    InheritSuperChainTests.calls.append("basemodel_create")
    return self_.browse(42)


def _noop_unlink(self_) -> None:
    InheritSuperChainTests.calls.append("basemodel_unlink")


class InheritSuperChainTests(unittest.TestCase):
    calls: list[str] = []

    def setUp(self) -> None:
        type(self).calls = []
        self.reg = Registry()
        self._orig_write = BaseModel.write
        self._orig_create = BaseModel.create
        self._orig_unlink = BaseModel.unlink
        BaseModel.write = _noop_write  # type: ignore[method-assign]
        BaseModel.create = _noop_create  # type: ignore[method-assign]
        BaseModel.unlink = _noop_unlink  # type: ignore[method-assign]

    def tearDown(self) -> None:
        BaseModel.write = self._orig_write  # type: ignore[method-assign]
        BaseModel.create = self._orig_create  # type: ignore[method-assign]
        BaseModel.unlink = self._orig_unlink  # type: ignore[method-assign]

    def _build_three_extensions(self, *, use_self_super: bool = False) -> type:
        calls = type(self).calls

        with self.reg.activate():
            class Root(models.Model):
                _name = "test.super.root"
                name = Char()

                def write(self, vals):
                    calls.append("root")
                    super().write(vals)

        with self.reg.activate():
            class ExtA(models.Model):
                _inherit = "test.super.root"
                note_a = Char()

                if use_self_super:

                    def write(self, vals):
                        calls.append("ext_a")
                        self.super().write(vals)

                else:

                    def write(self, vals):
                        calls.append("ext_a")
                        super().write(vals)

        with self.reg.activate():
            class ExtB(models.Model):
                _inherit = "test.super.root"
                note_b = Char()

        with self.reg.activate():
            class ExtC(models.Model):
                _inherit = "test.super.root"
                note_c = Char()

                if use_self_super:

                    def write(self, vals):
                        calls.append("ext_c")
                        self.super().write(vals)

                else:

                    def write(self, vals):
                        calls.append("ext_c")
                        super().write(vals)

        return self.reg["test.super.root"]

    def test_inherit_chain_metadata(self) -> None:
        cls = self._build_three_extensions()
        chain = self.reg.inherit_chain("test.super.root")
        self.assertEqual(len(chain), 4)
        self.assertEqual(chain[0].__name__, "Root")
        self.assertEqual(chain[-1].__name__, "ExtC")
        self.assertEqual(cls._inherit_chain, chain)

    def test_write_super_builtin(self) -> None:
        cls = self._build_three_extensions(use_self_super=False)
        env = _FakeEnv(self.reg)
        cls(env, (1,)).write({"name": "x"})
        self.assertEqual(self.calls, ["ext_c", "ext_a", "root", "basemodel_write"])

    def test_write_self_super(self) -> None:
        cls = self._build_three_extensions(use_self_super=True)
        env = _FakeEnv(self.reg)
        cls(env, (1,)).write({"name": "x"})
        self.assertEqual(self.calls, ["ext_c", "ext_a", "root", "basemodel_write"])

    def test_create_and_unlink_chains(self) -> None:
        calls = self.calls

        with self.reg.activate():
            class Root(models.Model):
                _name = "test.super.crud"
                name = Char()

                def create(self, vals):
                    calls.append("root_create")
                    return super().create(vals)

                def unlink(self):
                    calls.append("root_unlink")
                    super().unlink()

        with self.reg.activate():
            class Ext(models.Model):
                _inherit = "test.super.crud"

                def create(self, vals):
                    calls.append("ext_create")
                    return self.super().create(vals)

                def unlink(self):
                    calls.append("ext_unlink")
                    self.super().unlink()

        cls = self.reg["test.super.crud"]
        env = _FakeEnv(self.reg)
        rec = cls(env, ()).create({"name": "n"})
        self.assertEqual(rec._ids, (42,))
        self.assertEqual(
            calls[:3], ["ext_create", "root_create", "basemodel_create"]
        )

        calls.clear()
        cls(env, (7,)).unlink()
        self.assertEqual(calls, ["ext_unlink", "root_unlink", "basemodel_unlink"])

    def test_compute_super_chain(self) -> None:
        calls = self.calls

        with self.reg.activate():
            class Root(models.Model):
                _name = "test.super.compute"
                name = Char()

                @depends("name")
                def _compute_display_name(self):
                    calls.append("root_compute")
                    super()._compute_display_name()

        with self.reg.activate():
            class Ext(models.Model):
                _inherit = "test.super.compute"
                tag = Char()

                @depends("name", "tag")
                def _compute_display_name(self):
                    calls.append("ext_compute")
                    super()._compute_display_name()

        cls = self.reg["test.super.compute"]
        env = _FakeEnv(self.reg)
        env._in_compute = True
        cls(env, (1,))._compute_display_name()
        self.assertEqual(calls, ["ext_compute", "root_compute"])

    def test_vellum_mixin_in_chain(self) -> None:
        calls = self.calls

        with self.reg.activate():
            class Root(models.Model):
                _name = "test.super.vellum"
                name = Char()

                def write(self, vals):
                    calls.append("root")
                    super().write(vals)

        with self.reg.activate():
            class Ext(Vellum, models.Model):
                _inherit = "test.super.vellum"

                def write(self, vals):
                    calls.append("ext")
                    super().write(vals)

        cls = self.reg["test.super.vellum"]
        env = _FakeEnv(self.reg)
        cls(env, (1,)).write({"name": "x"})
        self.assertIn("ext", calls)
        self.assertIn("root", calls)
        self.assertIn("basemodel_write", calls)
        self.assertEqual(calls.index("ext"), 0)
        self.assertLess(calls.index("root"), calls.index("basemodel_write"))


if __name__ == "__main__":
    unittest.main()
