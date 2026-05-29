"""Unit tests for ``pyvelm.mail_template_fields``."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Integer, Many2one, One2many, Registry
from pyvelm.fields import Field
from pyvelm.env import Environment
from pyvelm.mail_template_fields import _collect_model_vars, _model_label, list_template_variables


class MailTemplateFieldsTests(unittest.TestCase):
    def test_model_label_unknown(self):
        env = MagicMock(registry={})
        self.assertEqual(_model_label(env, "missing"), "missing")

    def test_model_label_uses_description(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.label"
                _description = "Pretty Name"
                x = Char()

        env = Environment(None, reg)
        self.assertEqual(_model_label(env, "test.label"), "Pretty Name")

    def test_collect_skips_private_and_non_stored(self):
        from pyvelm import depends

        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.collect"
                name = Char()
                secret = Char()
                total = Integer(compute="_c", store=False)

                @depends("name")
                def _c(self):
                    pass

            M._fields["secret"].private = True

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.collect",
            prefix="object",
            label_prefix="M",
            depth=0,
            max_depth=2,
            out=out,
        )
        exprs = {v["expr"] for v in out}
        self.assertIn("object.name", exprs)
        self.assertNotIn("object.secret", exprs)
        self.assertNotIn("object.total", exprs)

    def test_collect_many2one_nested(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.country"
                code = Char()

            class Partner(BaseModel):
                _name = "test.partner"
                name = Char()
                country_id = Many2one("test.country")

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.partner",
            prefix="object",
            label_prefix="Partner",
            depth=0,
            max_depth=2,
            out=out,
        )
        exprs = {v["expr"] for v in out}
        self.assertIn("object.country_id", exprs)
        self.assertIn("object.country_id.code", exprs)

    def test_collect_skips_non_scalar_field_type(self):
        reg = Registry()

        class Weird(Field):
            sql_type = "text"

        with reg.activate():

            class M(BaseModel):
                _name = "test.weird"
                name = Char()
                odd = Weird()

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.weird",
            prefix="object",
            label_prefix="M",
            depth=0,
            max_depth=1,
            out=out,
        )
        exprs = {v["expr"] for v in out}
        self.assertIn("object.name", exprs)
        self.assertNotIn("object.odd", exprs)

    def test_collect_skips_non_scalar(self):
        reg = Registry()
        with reg.activate():

            class Line(BaseModel):
                _name = "test.line"
                name = Char()

            class Order(BaseModel):
                _name = "test.order"
                name = Char()
                line_ids = One2many("test.line", "order_id")

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.order",
            prefix="object",
            label_prefix="Order",
            depth=0,
            max_depth=2,
            out=out,
        )
        exprs = {v["expr"] for v in out}
        self.assertIn("object.name", exprs)
        self.assertNotIn("object.line_ids", exprs)

    def test_collect_permission_denied(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.perm"
                name = Char()

        env = Environment(None, reg, uid=1)
        env.check_access = MagicMock(side_effect=PermissionError)
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.perm",
            prefix="object",
            label_prefix="M",
            depth=0,
            max_depth=1,
            out=out,
        )
        self.assertEqual(out, [])

    def test_collect_skips_underscore_fields(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.underscore"
                name = Char()
                _hidden = Char()

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="test.underscore",
            prefix="object",
            label_prefix="M",
            depth=0,
            max_depth=1,
            out=out,
        )
        exprs = {v["expr"] for v in out}
        self.assertIn("object.name", exprs)
        self.assertNotIn("object._hidden", exprs)

    def test_collect_unknown_model(self):
        env = Environment(None, Registry(), uid=1)
        out: list = []
        _collect_model_vars(
            env,
            root="object",
            model_name="missing",
            prefix="object",
            label_prefix="M",
            depth=0,
            max_depth=1,
            out=out,
        )
        self.assertEqual(out, [])

    def test_list_template_variables_full(self):
        reg = Registry()
        with reg.activate():

            class User(BaseModel):
                _name = "res.users"
                login = Char()

            class Company(BaseModel):
                _name = "res.company"
                name = Char()

            class Partner(BaseModel):
                _name = "test.vars.partner"
                name = Char()
                email = Char()

        env = Environment(None, reg, uid=1)
        env._acl_bypass = True
        data = list_template_variables(env, "test.vars.partner")
        self.assertEqual(data["model"], "test.vars.partner")
        exprs = {v["expr"] for v in data["variables"]}
        self.assertIn("object.name", exprs)
        self.assertIn("user.login", exprs)
        self.assertIn("company.name", exprs)
        self.assertIn("ctx", exprs)


if __name__ == "__main__":
    unittest.main()
