"""Unit tests for ``pyvelm.mail_template_render``."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Many2one, Registry
from pyvelm.env import Environment
from pyvelm.mail_template_render import (
    _normalize_template_source,
    build_mail_template_context,
    render_mail_template_string,
)


class NormalizeTemplateTests(unittest.TestCase):
    def test_empty_source(self):
        self.assertEqual(_normalize_template_source(""), "")

    def test_legacy_dollar_braces(self):
        self.assertIn("{{ name }}", _normalize_template_source("Hi ${name}!"))


class RenderTemplateStringTests(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(render_mail_template_string("  ", {"x": 1}), "")

    def test_renders_with_context(self):
        out = render_mail_template_string("Hello {{ name }}", {"name": "World"})
        self.assertEqual(out, "Hello World")


class BuildContextTests(unittest.TestCase):
    def test_object_from_record(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.ctx.partner"
                name = Char()

        env = Environment(None, reg, uid=1)
        rec = Partner(env, (1,))
        env.cache.set("test.ctx.partner", 1, "id", 1)
        ctx = build_mail_template_context(
            env, model="test.ctx.partner", record=rec
        )
        self.assertEqual(ctx["object"]._ids, (1,))

    def test_object_from_model_when_no_record(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.ctx.partner2"
                name = Char()

        env = Environment(None, reg, uid=None)
        ctx = build_mail_template_context(env, model="test.ctx.partner2", record=None)
        self.assertEqual(ctx["object"]._name, "test.ctx.partner2")

    def test_object_none_when_unknown(self):
        env = MagicMock(registry={}, uid=None)
        ctx = build_mail_template_context(env, model="missing", record=None)
        self.assertIsNone(ctx["object"])

    def test_user_and_company_resolution(self):
        reg = Registry()
        with reg.activate():

            class User(BaseModel):
                _name = "res.users"
                login = Char()
                company_id = Many2one("res.company")

            class Company(BaseModel):
                _name = "res.company"
                name = Char()

        env = Environment(None, reg, uid=1, context={})
        env.cache.set("res.users", 1, "id", 1)
        env.cache.set("res.users", 1, "company_id", 2)
        env.cache.set("res.company", 2, "id", 2)
        env.cache.set("res.company", 2, "name", "ACME")
        ctx = build_mail_template_context(env, model="", record=None)
        self.assertEqual(ctx["user"]._ids, (1,))
        self.assertEqual(ctx["company"]._ids, (2,))

    def test_company_from_env_company_id(self):
        reg = Registry()
        with reg.activate():

            class Company(BaseModel):
                _name = "res.company"
                name = Char()

        env = Environment(None, reg, uid=None, context={"company_id": 5})
        env.cache.set("res.company", 5, "id", 5)
        ctx = build_mail_template_context(env, model="", record=None)
        self.assertEqual(ctx["company"]._ids, (5,))

    def test_company_fallback_search(self):
        reg = Registry()
        with reg.activate():

            class Company(BaseModel):
                _name = "res.company"
                name = Char()

        env = Environment(None, reg, uid=None)
        Co = reg["res.company"]
        env.cache.set("res.company", 3, "id", 3)
        with unittest.mock.patch.object(
            Co, "search", return_value=Co(env, (3,))
        ) as search:
            ctx = build_mail_template_context(env, model="", record=None)
        search.assert_called_once()
        self.assertEqual(ctx["company"]._ids, (3,))

    def test_extra_ctx_dict(self):
        env = MagicMock(registry={}, uid=None)
        ctx = build_mail_template_context(
            env, model="", record=None, extra={"key": "val"}
        )
        self.assertEqual(ctx["ctx"], {"key": "val"})

    def test_render_syntax_error(self):
        with self.assertRaises(ValueError):
            render_mail_template_string("{{ broken", {"x": 1})


if __name__ == "__main__":
    unittest.main()
