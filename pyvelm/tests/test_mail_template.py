"""Email template rendering and send integration."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm.mail_template_fields import list_template_variables
from pyvelm.mail_template_render import (
    build_mail_template_context,
    render_mail_template_string,
)
from pyvelm.tests._mail import register_mail_template, seed_author
from pyvelm.tests.support.db import DatabaseTestCase


class MailTemplateRenderTests(unittest.TestCase):
    def test_jinja_and_legacy_syntax(self):
        ctx = {"object": type("O", (), {"name": "Acme"})()}
        out = render_mail_template_string("Hello ${object.name}!", ctx)
        self.assertEqual(out, "Hello Acme!")
        out2 = render_mail_template_string("Hi {{ object.name }}", ctx)
        self.assertEqual(out2, "Hi Acme")

    def test_syntax_error_raises(self):
        with self.assertRaises(ValueError):
            render_mail_template_string("{{ object.name }", {"object": None})

    def test_list_template_variables(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.mail.partner"
                name = Char()
                email = Char()

        env = Environment(object(), reg, uid=None)
        env._acl_bypass = True
        data = list_template_variables(env, "test.mail.partner")
        exprs = {v["expr"] for v in data["variables"]}
        self.assertIn("object.name", exprs)
        self.assertIn("object.email", exprs)
        self.assertIn("ctx", exprs)

    def test_build_context_without_db(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.mail.partner"
                name = Char()
                email = Char()

        env = Environment(object(), reg, uid=None)
        rec = env["test.mail.partner"]
        ctx = build_mail_template_context(env, model="test.mail.partner", record=rec)
        self.assertIn("object", ctx)
        self.assertIn("company", ctx)


class MailTemplateSendTests(DatabaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_send_mail_queues_html_message(self):
        from pyvelm.mail import MailThread, Message

        reg = Registry()
        with reg.activate():
            register_mail_template(reg)

            class Partner(MailThread, BaseModel):
                _name = "test.mail.tpl.partner"
                name = Char(default="Demo")
                email = Char(default="demo@example.com")

        reg.init_db(self.conn)
        self.conn.commit()
        env = Environment(self.conn, reg, uid=1)
        env._acl_bypass = True
        seed_author(env)
        partner = env["test.mail.tpl.partner"].create(
            {"name": "Acme Corp", "email": "billing@acme.example"}
        )
        tpl = env["mail.template"].create(
            {
                "name": "Partner welcome",
                "model": "test.mail.tpl.partner",
                "subject": "Hello {{ object.name }}",
                "body_html": (
                    "<p>Welcome <strong>{{ object.name }}</strong></p>"
                    "<p>Reach us at {{ object.email }}</p>"
                ),
                "active": True,
            }
        )
        msg = partner.send_mail(tpl, to="billing@acme.example")
        self.assertTrue(msg.body_is_html)
        self.assertIn("Acme Corp", msg.body)
        self.assertEqual(msg.subject, "Hello Acme Corp")
        self.assertEqual(msg.recipient_email, "billing@acme.example")
        self.assertEqual(msg.state, "outgoing")
        self.assertEqual(msg.template_id.id, tpl.id)

        backend = MagicMock()
        stats = Message.dispatch_outgoing(env, backend=backend)
        self.assertGreaterEqual(stats["sent"], 1)
        sent_bodies = [
            c.kwargs.get("body_html", "") for c in backend.send.call_args_list
        ]
        self.assertTrue(any("Acme Corp" in b for b in sent_bodies))

        msg2 = env["mail.message"].browse(msg.id)
        self.assertEqual(msg2.state, "sent")


if __name__ == "__main__":
    unittest.main()
