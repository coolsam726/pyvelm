"""Tests for the mail backend's multi-recipient support and the
``mail.compose.message`` composer model.

Schema-touching tests are guarded by ``PYVELM_DSN`` like the other
mail tests; pure helper / address-splitting tests stay unit-only so
they run in CI without a database.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Environment, Registry

DSN = os.environ.get("PYVELM_DSN")


def _import_split_addresses():
    """Late import: ``pyvelm.mail`` defines models at import time, so the
    helper has to be pulled in after a registry is active (or from a test
    where the model registration is a no-op because the registry is
    already populated by the time the import lands)."""
    reg = Registry()
    with reg.activate():
        from pyvelm.mail import _split_addresses
    return _split_addresses

try:
    import psycopg
except ImportError:
    psycopg = None


class AddressSplitTests(unittest.TestCase):
    """``_split_addresses`` is the parsing rule the backends depend on."""

    @classmethod
    def setUpClass(cls):
        cls._split = staticmethod(_import_split_addresses())

    def test_empty_returns_empty_list(self):
        split = type(self)._split
        self.assertEqual(split(None), [])
        self.assertEqual(split(""), [])
        self.assertEqual(split("   "), [])

    def test_single_address(self):
        split = type(self)._split
        self.assertEqual(split("a@x.com"), ["a@x.com"])

    def test_comma_separated_with_whitespace(self):
        split = type(self)._split
        self.assertEqual(
            split("a@x.com, b@y.com ,c@z.com"),
            ["a@x.com", "b@y.com", "c@z.com"],
        )

    def test_semicolon_treated_as_separator(self):
        split = type(self)._split
        self.assertEqual(
            split("a@x.com; b@y.com"),
            ["a@x.com", "b@y.com"],
        )

    def test_blank_chunks_dropped(self):
        split = type(self)._split
        self.assertEqual(
            split("a@x.com,,,b@y.com,"),
            ["a@x.com", "b@y.com"],
        )


@unittest.skipUnless(DSN and psycopg, "needs postgres")
class MailMessageCcBccTests(unittest.TestCase):
    def test_dispatch_forwards_cc_bcc_reply_to(self):
        reg = Registry()
        with reg.activate():
            class User(BaseModel):
                _name = "res.users"
                login = Char()

            from pyvelm.actions import ServerAction
            from pyvelm.automation import AutomatedAction
            from pyvelm.mail_template import MailTemplate
            from pyvelm.mail import MailThread, Message

            for cls in (ServerAction, AutomatedAction, Message, MailTemplate):
                reg.register(cls)

            class Partner(MailThread, BaseModel):
                _name = "test.compose.partner"
                name = Char(default="Demo")
                email = Char()

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True

            partner = env["test.compose.partner"].create(
                {"name": "Acme", "email": "ops@acme.example"}
            )
            msg = partner._send_rendered_mail(
                subject="Hello",
                body_html="<p>hi</p>",
                recipient_email="primary@acme.example, second@acme.example",
                cc="cc1@acme.example",
                bcc="bcc1@acme.example",
                reply_to="replyto@acme.example",
            )
            self.assertEqual(msg.recipient_cc, "cc1@acme.example")
            self.assertEqual(msg.recipient_bcc, "bcc1@acme.example")
            self.assertEqual(msg.reply_to, "replyto@acme.example")

            backend = MagicMock()
            stats = env.registry["mail.message"].dispatch_outgoing(env, backend=backend)
            self.assertEqual(stats["sent"], 1)
            kwargs = backend.send.call_args.kwargs
            self.assertEqual(kwargs["cc"], "cc1@acme.example")
            self.assertEqual(kwargs["bcc"], "bcc1@acme.example")
            self.assertEqual(kwargs["reply_to"], "replyto@acme.example")
            self.assertEqual(
                kwargs["to"], "primary@acme.example, second@acme.example"
            )


@unittest.skipUnless(DSN and psycopg, "needs postgres")
class MailComposeTests(unittest.TestCase):
    """Composer model lifecycle: launch / apply template / send / save as.

    The framework models (Message, MailTemplate, MailCompose) are imported
    via a normal Python ``import``, which only executes the module body
    once per process. To support multiple test methods that each spin up
    a fresh ``Registry``, we re-register the already-imported classes
    explicitly — the registry is just a dict-of-class-objects, so this is
    the same shape the metaclass would do during a first-time import.
    """

    def _registry(self):
        reg = Registry()
        with reg.activate():
            class User(BaseModel):
                _name = "res.users"
                login = Char()

            # Stub ir.attachment — the composer's attachment_ids M2m needs
            # the comodel registered. In a real app this is the base module's
            # ir.attachment with file storage; the composer only reads
            # ``fetch_content`` at dispatch time, which these tests don't
            # exercise.
            class Attachment(BaseModel):
                _name = "ir.attachment"
                name = Char()

            from pyvelm.actions import ServerAction
            from pyvelm.automation import AutomatedAction
            from pyvelm.mail import MailThread, Message
            from pyvelm.mail_template import MailTemplate
            from pyvelm.mail_compose import MailCompose

            for cls in (ServerAction, AutomatedAction, Message, MailTemplate, MailCompose):
                reg.register(cls)

            class Partner(MailThread, BaseModel):
                _name = "test.compose.partner2"
                name = Char(default="Demo")
                email = Char()
        return reg

    def test_launch_autofills_to_from_email_field(self):
        reg = self._registry()
        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            partner = env["test.compose.partner2"].create(
                {"name": "Acme", "email": "billing@acme.example"}
            )
            Compose = env.registry["mail.compose.message"]
            composer = Compose.launch(
                env, model="test.compose.partner2", res_id=partner.id
            )
            self.assertEqual(composer.recipient_to, "billing@acme.example")
            self.assertEqual(composer.model, "test.compose.partner2")
            self.assertEqual(composer.res_id, partner.id)
            self.assertEqual(composer.state, "draft")

    def test_launch_with_template_renders_subject_and_body(self):
        reg = self._registry()
        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            partner = env["test.compose.partner2"].create(
                {"name": "Acme", "email": "billing@acme.example"}
            )
            tpl = env["mail.template"].create(
                {
                    "name": "Welcome",
                    "model": "test.compose.partner2",
                    "subject": "Hello {{ object.name }}",
                    "body_html": "<p>Hi {{ object.name }}</p>",
                    "active": True,
                }
            )
            Compose = env.registry["mail.compose.message"]
            composer = Compose.launch(
                env,
                model="test.compose.partner2",
                res_id=partner.id,
                template_id=tpl.id,
            )
            self.assertEqual(composer.subject, "Hello Acme")
            self.assertIn("Hi Acme", composer.body_html or "")

    def test_action_send_queues_outgoing_message(self):
        reg = self._registry()
        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            partner = env["test.compose.partner2"].create(
                {"name": "Acme", "email": "billing@acme.example"}
            )
            Compose = env.registry["mail.compose.message"]
            composer = Compose.launch(
                env, model="test.compose.partner2", res_id=partner.id
            )
            composer.write(
                {
                    "subject": "Manual subject",
                    "body_html": "<p>Manual body</p>",
                    "recipient_cc": "cc@acme.example",
                    "recipient_bcc": "bcc@acme.example",
                    "reply_to": "noreply@acme.example",
                }
            )
            composer.action_send()
            self.assertEqual(composer.state, "sent")
            msgs = env["mail.message"].search(
                [("model", "=", "test.compose.partner2"), ("res_id", "=", partner.id)]
            )
            self.assertEqual(len(msgs), 1)
            msg = env["mail.message"].browse(msgs._ids[0])
            self.assertEqual(msg.subject, "Manual subject")
            self.assertEqual(msg.recipient_cc, "cc@acme.example")
            self.assertEqual(msg.recipient_bcc, "bcc@acme.example")
            self.assertEqual(msg.reply_to, "noreply@acme.example")
            self.assertEqual(msg.state, "outgoing")

    def test_action_save_as_template_creates_template(self):
        reg = self._registry()
        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            partner = env["test.compose.partner2"].create(
                {"name": "Acme", "email": "billing@acme.example"}
            )
            Compose = env.registry["mail.compose.message"]
            composer = Compose.launch(
                env, model="test.compose.partner2", res_id=partner.id
            )
            composer.write({"subject": "Reusable", "body_html": "<p>Body</p>"})
            tpl = composer.action_save_as_template(name="My template")
            self.assertEqual(tpl.name, "My template")
            self.assertEqual(tpl.model, "test.compose.partner2")
            self.assertEqual(tpl.subject, "Reusable")
            self.assertIn("Body", tpl.body_html or "")


if __name__ == "__main__":
    unittest.main()
