"""Unit tests for ``pyvelm.mail_chatter`` (no database)."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from pyvelm import mail_chatter


class LabelAndFilterTests(unittest.TestCase):
    def test_subtype_labels(self):
        self.assertEqual(
            mail_chatter._subtype_label("mail_tracking"), "Field change"
        )
        self.assertEqual(
            mail_chatter._subtype_label("", message_type="email"), "Email"
        )
        self.assertEqual(
            mail_chatter._subtype_label("note"), "Note"
        )
        self.assertEqual(
            mail_chatter._subtype_label("", message_type="notification"), "System"
        )
        self.assertEqual(mail_chatter._subtype_label("other"), "Log")

    def test_email_state_labels(self):
        self.assertEqual(mail_chatter._email_state_label("sent"), "Sent")
        self.assertEqual(mail_chatter._email_state_label("failed"), "Failed")
        self.assertEqual(mail_chatter._email_state_label("outgoing"), "Queued")
        self.assertEqual(mail_chatter._email_state_label(None), "")

    def test_parse_attachment_ids(self):
        self.assertEqual(mail_chatter._parse_attachment_ids([]), [])
        self.assertEqual(
            mail_chatter._parse_attachment_ids(["1", "2,3", " 4 "]),
            [1, 2, 3, 4],
        )
        self.assertEqual(
            mail_chatter._parse_attachment_ids(["1", "1"]),
            [1],
        )
        self.assertEqual(mail_chatter._parse_attachment_ids(["", "5"]), [5])

    def test_author_initials(self):
        self.assertEqual(mail_chatter._author_initials(""), "?")
        self.assertEqual(mail_chatter._author_initials("Ada Lovelace"), "AL")
        self.assertEqual(mail_chatter._author_initials("Ada"), "AD")

    def test_normalize_filter_invalid(self):
        self.assertEqual(mail_chatter._normalize_filter("bogus"), "all")


class FilterMatchTests(unittest.TestCase):
    def test_matches_filter_branches(self):
        base = {"subtype": "note", "message_type": "comment", "recipient_email": ""}
        self.assertTrue(mail_chatter._matches_filter(base, "all"))
        self.assertTrue(
            mail_chatter._matches_filter({**base, "subtype": "mail_tracking"}, "tracking")
        )
        self.assertTrue(
            mail_chatter._matches_filter(
                {**base, "recipient_email": "a@b.c"}, "emails"
            )
        )
        self.assertTrue(
            mail_chatter._matches_filter(
                {**base, "message_type": "email"}, "emails"
            )
        )
        self.assertTrue(mail_chatter._matches_filter(base, "notes"))
        self.assertFalse(
            mail_chatter._matches_filter(
                {**base, "subtype": "mail_tracking"}, "notes"
            )
        )
        self.assertTrue(mail_chatter._matches_filter(base, "other"))


class AttachmentsAndEventsTests(unittest.TestCase):
    def test_attachments_no_registry(self):
        env = MagicMock(registry={})
        self.assertEqual(mail_chatter._attachments_for_messages(env, [1]), {})

    def test_attachments_permission_denied(self):
        env = MagicMock(registry={"ir.attachment": object})
        env.check_access = MagicMock(side_effect=PermissionError)
        self.assertEqual(mail_chatter._attachments_for_messages(env, [1]), {})

    def test_attachments_groups_by_message(self):
        env = MagicMock(registry={"ir.attachment": object})
        env.check_access = MagicMock()
        att = MagicMock(
            id=5,
            res_id=10,
            name="doc.pdf",
            datas_fname=None,
            mimetype="application/pdf",
            file_size=100,
        )
        Att = MagicMock()
        Att.search.return_value = [att]
        env.__getitem__ = MagicMock(return_value=Att)
        out = mail_chatter._attachments_for_messages(env, [10])
        self.assertEqual(len(out[10]), 1)
        self.assertIn("/api/attachment/5/download", out[10][0]["download_url"])

    def test_attachments_skips_missing_res_id(self):
        env = MagicMock(registry={"ir.attachment": object})
        env.check_access = MagicMock()
        att = MagicMock(
            id=6,
            res_id=None,
            name="x",
            datas_fname=None,
            mimetype="",
            file_size=0,
        )
        Att = MagicMock()
        Att.search.return_value = [att]
        env.__getitem__ = MagicMock(return_value=Att)
        self.assertEqual(mail_chatter._attachments_for_messages(env, [1]), {})

    def test_message_event(self):
        env = MagicMock()
        msg = MagicMock(
            id=1,
            body="Hello",
            subtype="note",
            message_type="comment",
            recipient_email="",
            author_id=None,
            date=datetime(2026, 1, 1, 12, 0),
            subject="",
            state="outgoing",
        )
        with (
            patch("pyvelm.mail_chatter.classify_workflow_body", return_value=("log", "")),
            patch("pyvelm.mail_chatter._author_name", return_value="Ada"),
            patch("pyvelm.mail_chatter._format_time", return_value="Jan 1"),
        ):
            ev = mail_chatter._message_event(msg, env, att_map={})
        self.assertEqual(ev["author_initials"], "AD")
        self.assertEqual(ev["subtype_label"], "Note")
        self.assertEqual(ev["attachments"], [])


class RecordChatterTests(unittest.TestCase):
    def test_record_messages_no_mail_model(self):
        env = MagicMock(registry={})
        self.assertEqual(
            mail_chatter.record_chatter_messages(env, "m", 1), []
        )

    def test_record_messages_permission_denied(self):
        env = MagicMock(registry={"mail.message": object})
        env.check_access = MagicMock(side_effect=PermissionError)
        self.assertEqual(
            mail_chatter.record_chatter_messages(env, "m", 1), []
        )

    def test_record_messages_filters_workflow(self):
        env = MagicMock(registry={"mail.message": object})
        env.check_access = MagicMock()
        m1 = MagicMock(
            id=1,
            body="Note",
            subtype="note",
            message_type="comment",
            recipient_email="",
            author_id=None,
            date=None,
            subject="",
            state="",
        )
        m2 = MagicMock(
            id=2,
            body="WF",
            subtype="workflow",
            message_type="notification",
            recipient_email="",
            author_id=None,
            date=None,
            subject="",
            state="",
        )
        Msg = MagicMock()
        Msg.search.return_value = [m1, m2]
        env.__getitem__ = MagicMock(return_value=Msg)
        with (
            patch("pyvelm.mail_chatter._attachments_for_messages", return_value={}),
            patch(
                "pyvelm.mail_chatter._message_event",
                side_effect=lambda m, e, att_map: {"id": m.id, "at": "1", "body": m.body},
            ),
            patch("pyvelm.mail_chatter._matches_filter", return_value=True),
        ):
            out = mail_chatter.record_chatter_messages(env, "m", 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["body"], "Note")


class FormChatterContextTests(unittest.TestCase):
    def test_disabled_or_missing_res_id(self):
        env = MagicMock(registry={"m": object})
        self.assertIsNone(mail_chatter.form_chatter_context(env, "m", 0, enabled=True))
        self.assertIsNone(
            mail_chatter.form_chatter_context(env, "m", 1, enabled=False)
        )

    def test_unknown_model(self):
        env = MagicMock(registry={})
        self.assertIsNone(
            mail_chatter.form_chatter_context(env, "m", 1, enabled=True)
        )

    def test_full_context_with_compose(self):
        env = MagicMock(registry={"doc.model": object, "mail.compose.message": object})
        env.check_access = MagicMock()
        with (
            patch(
                "pyvelm.mail_chatter.record_chatter_messages",
                return_value=[{"id": 1}],
            ),
        ):
            ctx = mail_chatter.form_chatter_context(
                env, "doc.model", 5, enabled=True, composer_mode="email"
            )
        self.assertTrue(ctx["enabled"])
        self.assertEqual(ctx["composer_mode"], "email")
        self.assertIn("compose/launch", ctx["compose_url"])
        self.assertTrue(ctx["can_post"])

    def test_context_without_write_permission(self):
        env = MagicMock(registry={"doc.model": object})
        env.check_access = MagicMock(side_effect=PermissionError)
        with patch("pyvelm.mail_chatter.record_chatter_messages", return_value=[]):
            ctx = mail_chatter.form_chatter_context(env, "doc.model", 1, enabled=True)
        self.assertFalse(ctx["can_post"])
        self.assertEqual(ctx["compose_url"], "")


class PostChatterMessageTests(unittest.TestCase):
    def _mail_thread_env(self):
        from pyvelm import BaseModel, Char, Registry
        from pyvelm.env import Environment
        from pyvelm.tests._mail import register_mail_message

        reg = Registry()
        with reg.activate():
            from pyvelm.mail import MailThread

            register_mail_message(reg)

            class Doc(MailThread, BaseModel):
                _name = "test.chatter.post"
                name = Char()

        env = Environment(None, reg, uid=1)
        return reg, Doc, env

    def test_requires_body(self):
        env = MagicMock(registry={"m": object})
        with self.assertRaises(ValueError):
            mail_chatter.post_chatter_message(env, "m", 1, "  ")

    def test_unknown_model(self):
        env = MagicMock(registry={})
        with self.assertRaises(ValueError):
            mail_chatter.post_chatter_message(env, "m", 1, "hi")

    def test_not_mail_thread(self):
        from pyvelm import BaseModel, Char, Registry
        from pyvelm.env import Environment

        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "plain.model"
                name = Char()

        env = Environment(None, reg, uid=1)
        with reg.activate(), self.assertRaises(ValueError):
            mail_chatter.post_chatter_message(env, "plain.model", 1, "hi")

    def test_record_not_found(self):
        reg, Doc, env = self._mail_thread_env()
        with (
            reg.activate(),
            patch.object(Doc, "browse", return_value=Doc(env, ())),
            self.assertRaises(ValueError),
        ):
            mail_chatter.post_chatter_message(env, "test.chatter.post", 999, "hi")

    def test_post_note(self):
        reg, Doc, env = self._mail_thread_env()
        env.cache.set("test.chatter.post", 1, "id", 1)
        with reg.activate(), patch.object(Doc, "message_post") as post:
            mail_chatter.post_chatter_message(
                env, "test.chatter.post", 1, "Note body"
            )
        post.assert_called_once()

    def test_post_email_requires_address(self):
        reg, _Doc, env = self._mail_thread_env()
        env.cache.set("test.chatter.post", 1, "id", 1)
        with reg.activate(), self.assertRaises(ValueError):
            mail_chatter.post_chatter_message(
                env, "test.chatter.post", 1, "Body", action="email"
            )

    def test_post_email_notify(self):
        reg, Doc, env = self._mail_thread_env()
        env.cache.set("test.chatter.post", 1, "id", 1)
        with reg.activate(), patch.object(Doc, "notify") as notify:
            mail_chatter.post_chatter_message(
                env,
                "test.chatter.post",
                1,
                "Email body",
                action="email",
                recipient_email="a@b.c",
                subject="Sub",
            )
        notify.assert_called_once()

    def test_post_note_alias(self):
        with patch("pyvelm.mail_chatter.post_chatter_message") as post:
            mail_chatter.post_chatter_note(MagicMock(), "m", 1, "x")
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
