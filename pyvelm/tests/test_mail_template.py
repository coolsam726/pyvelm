"""Email template rendering and send integration."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm.mail_template_fields import list_template_variables
from pyvelm.tests._mail import register_mail_template
from pyvelm.mail_template_render import (
    build_mail_template_context,
    render_mail_template_string,
)

DSN = os.environ.get("PYVELM_DSN")

try:
    import psycopg
except ImportError:
    psycopg = None


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


@unittest.skipUnless(DSN and psycopg, "needs postgres")
class MailTemplateSendTests(unittest.TestCase):
    def test_send_mail_queues_html_message(self):
        from pyvelm.mail import MailThread, Message

        reg = Registry()
        with reg.activate():
            register_mail_template(reg)

            class Partner(MailThread, BaseModel):
                _name = "test.mail.tpl.partner"
                name = Char(default="Demo")
                email = Char(default="demo@example.com")

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
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
            self.assertEqual(stats["sent"], 1)
            backend.send.assert_called_once()
            kwargs = backend.send.call_args.kwargs
            self.assertIn("Acme Corp", kwargs["body_html"])
            self.assertEqual(kwargs["to"], "billing@acme.example")

            msg2 = env["mail.message"].browse(msg.id)
            self.assertEqual(msg2.state, "sent")


if __name__ == "__main__":
    unittest.main()
