"""General chatter panel, filters, and POST route."""
from __future__ import annotations

import os
import unittest

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm import mail_chatter
from pyvelm.tests._mail import register_mail_message

DSN = os.environ.get("PYVELM_DSN")

try:
    import psycopg
except ImportError:
    psycopg = None


class ChatterContextTests(unittest.TestCase):
    def test_form_context_disabled_without_mail_thread(self):
        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "test.chatter.plain"
                name = Char()

        env = Environment(object(), reg, uid=1)
        ctx = mail_chatter.form_chatter_context(
            env, "test.chatter.plain", 1, enabled=False
        )
        self.assertIsNone(ctx)

    def test_author_initials(self):
        self.assertEqual(mail_chatter._author_initials("Ada Lovelace"), "AL")
        self.assertEqual(mail_chatter._author_initials(""), "?")

    def test_normalize_filter(self):
        self.assertEqual(mail_chatter._normalize_filter("notes"), "notes")
        self.assertEqual(mail_chatter._normalize_filter("bogus"), "all")

    def test_matches_filter_categories(self):
        note = {"subtype": "note", "recipient_email": "", "message_type": "comment"}
        track = {"subtype": "mail_tracking", "recipient_email": "", "message_type": "notification"}
        email = {"subtype": "email", "recipient_email": "a@b.c", "message_type": "email"}
        self.assertTrue(mail_chatter._matches_filter(note, "notes"))
        self.assertFalse(mail_chatter._matches_filter(track, "notes"))
        self.assertTrue(mail_chatter._matches_filter(track, "tracking"))
        self.assertTrue(mail_chatter._matches_filter(email, "emails"))


@unittest.skipUnless(DSN and psycopg, "needs postgres")
class ChatterWriteTests(unittest.TestCase):
    def test_post_note_and_render(self):
        from pyvelm.mail import MailThread
        from pyvelm.render import render_chatter_panel

        reg = Registry()
        with reg.activate():

            class Doc(MailThread, BaseModel):
                _name = "test.chatter.doc"
                name = Char()

            register_mail_message(reg)

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            doc = env["test.chatter.doc"].create({"name": "A"})
            mail_chatter.post_chatter_message(
                env, "test.chatter.doc", doc.id, "Hello from test"
            )
            html = render_chatter_panel(env, "test.chatter.doc", doc.id)
            self.assertNotIn("pv-chatter-root", html)
            self.assertIn("Hello from test", html)
            self.assertIn("Activity", html)
            self.assertIn("Log note", html)

    def test_excludes_workflow_subtype(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Doc(MailThread, BaseModel):
                _name = "test.chatter.filter"
                name = Char()

            register_mail_message(reg)

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            doc = env["test.chatter.filter"].create({"name": "X"})
            Message = env["mail.message"]
            Message.create({
                "model": "test.chatter.filter",
                "res_id": doc.id,
                "body": "User note",
                "subtype": "note",
            })
            Message.create({
                "model": "test.chatter.filter",
                "res_id": doc.id,
                "body": "Workflow started",
                "subtype": "workflow",
            })
            msgs = mail_chatter.record_chatter_messages(
                env, "test.chatter.filter", doc.id
            )
            self.assertEqual(len(msgs), 1)
            self.assertIn("User note", msgs[0]["body"])

    def test_email_filter_and_notify(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Doc(MailThread, BaseModel):
                _name = "test.chatter.email"
                name = Char()

            register_mail_message(reg)

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            env._acl_bypass = True
            doc = env["test.chatter.email"].create({"name": "E"})
            mail_chatter.post_chatter_message(
                env,
                "test.chatter.email",
                doc.id,
                "Please review",
                action="email",
                recipient_email="reviewer@example.com",
                subject="Review",
            )
            emails = mail_chatter.record_chatter_messages(
                env, "test.chatter.email", doc.id, filter_key="emails"
            )
            self.assertEqual(len(emails), 1)
            self.assertEqual(emails[0]["recipient_email"], "reviewer@example.com")
            self.assertEqual(emails[0]["email_state"], "Queued")
            notes = mail_chatter.record_chatter_messages(
                env, "test.chatter.email", doc.id, filter_key="notes"
            )
            self.assertEqual(len(notes), 0)


if __name__ == "__main__":
    unittest.main()
