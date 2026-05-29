"""Additional unit tests for ``pyvelm.mail`` (backends + dispatcher + MailThread)."""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Registry
from pyvelm.env import Cache
from pyvelm.tests._mail import register_mail_message, register_mail_template


def _mail_registry():
    reg = Registry()
    with reg.activate():
        register_mail_message(reg)
    return reg


def _thread_registry(*, with_attachment: bool = False, with_template: bool = False):
    from pyvelm.mail import MailThread

    reg = _mail_registry()
    with reg.activate():
        if with_attachment:

            class Attachment(BaseModel):
                _name = "ir.attachment"
                name = Char()

            reg.register(Attachment)
        if with_template:
            register_mail_template(reg)

        class Partner(MailThread, BaseModel):
            _name = "test.mail.partner"
            name = Char()

    return reg, Partner


class _ThreadEnv:
    """Minimal env stub so ``env['mail.message']`` works like production."""

    def __init__(self, registry, models: dict, *, uid: int = 1):
        self.registry = registry
        self.uid = uid
        self.cache = Cache()
        self._models = models

    def __getitem__(self, name: str):
        return self._models[name]


def _partner(reg, Partner, env, rid: int):
    env.cache.set(Partner._name, rid, "id", rid)
    return Partner(env, (rid,))


def _mock_thread_env(
    reg,
    *,
    uid: int = 1,
    with_users: bool = True,
    with_template: bool = True,
):
    """Environment stub wired for MailThread.message_post / notify / send_mail."""
    created: list[MagicMock] = []

    def _create(vals):
        msg = MagicMock()
        msg.id = len(created) + 1
        for key, value in vals.items():
            setattr(msg, key, value)
        created.append(msg)
        return msg

    msg_model = MagicMock()
    msg_model.create.side_effect = _create
    msg_model.search.return_value = MagicMock(ids=[10, 11])

    att_model = MagicMock()
    att_row1 = MagicMock()
    att_row2 = MagicMock()
    att_model.browse.return_value = [att_row1, att_row2]

    tpl_model = MagicMock()
    tpl_rec = MagicMock()
    tpl_rec._ids = (3,)
    tpl_rec.send_mail.return_value = MagicMock(id=99)
    tpl_model.browse.return_value = tpl_rec

    models: dict = {
        "mail.message": msg_model,
        "ir.attachment": att_model,
    }
    if with_template:
        models["mail.template"] = tpl_model
    if with_users:
        models["res.users"] = MagicMock()

    registry = dict(reg._models)
    if not with_users:
        registry.pop("res.users", None)
    if not with_template:
        registry.pop("mail.template", None)

    env = _ThreadEnv(registry, models, uid=uid)
    return env, msg_model, att_row1, att_row2, tpl_model, tpl_rec, created


class SplitAddressesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = Registry()
        with reg.activate():
            from pyvelm.mail import _split_addresses

            cls.split = staticmethod(_split_addresses)

    def test_empty_and_none(self):
        self.assertEqual(self.split(None), [])
        self.assertEqual(self.split(""), [])

    def test_semicolon_and_blanks(self):
        self.assertEqual(self.split("a@x.com; b@y.com"), ["a@x.com", "b@y.com"])
        self.assertEqual(self.split("  ,  "), [])


class BackendTests(unittest.TestCase):
    def test_disabled_backend_noop(self):
        from pyvelm.mail import DisabledBackend

        DisabledBackend().send(to="a@x.com", subject="Hi", body="x")

    def test_console_backend_logs(self):
        from pyvelm.mail import ConsoleBackend

        with self.assertLogs("pyvelm.mail", level="INFO") as logs:
            ConsoleBackend().send(
                to="a@x.com",
                subject="Hello",
                body="plain",
                body_html="<p>html</p>",
                cc="cc@x.com",
                bcc="bcc@x.com",
                reply_to="reply@x.com",
                attachments=[object()],
            )
        text = "\n".join(logs.output)
        self.assertIn("a@x.com", text)
        self.assertIn("[html]", text)

    def test_console_backend_truncates_long_body(self):
        from pyvelm.mail import ConsoleBackend

        with self.assertLogs("pyvelm.mail", level="INFO"):
            ConsoleBackend().send(
                to="a@x.com",
                subject="Hi",
                body="x" * 250,
            )

    def test_load_backend_variants(self):
        from pyvelm.mail import ConsoleBackend, DisabledBackend, SmtpBackend, _load_backend

        with patch.dict(os.environ, {"PYVELM_MAIL_BACKEND": "disabled"}, clear=False):
            backend, default_from = _load_backend()
            self.assertIsInstance(backend, DisabledBackend)
            self.assertIsNone(default_from)

        with patch.dict(os.environ, {"PYVELM_MAIL_BACKEND": "console"}, clear=False):
            backend, _ = _load_backend()
            self.assertIsInstance(backend, ConsoleBackend)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PYVELM_MAIL_BACKEND", None)
            backend, _ = _load_backend()
            self.assertIsInstance(backend, ConsoleBackend)

        with patch.dict(
            os.environ,
            {
                "PYVELM_MAIL_BACKEND": "smtp",
                "PYVELM_SMTP_HOST": "smtp.test",
                "PYVELM_SMTP_PORT": "2525",
                "PYVELM_SMTP_FROM": "from@test",
                "PYVELM_SMTP_USE_TLS": "0",
            },
            clear=False,
        ):
            backend, default_from = _load_backend()
            self.assertIsInstance(backend, SmtpBackend)
            self.assertEqual(default_from, "from@test")

        with patch.dict(
            os.environ, {"PYVELM_MAIL_BACKEND": "smtp"}, clear=False
        ):
            os.environ.pop("PYVELM_SMTP_HOST", None)
            with self.assertRaises(RuntimeError):
                _load_backend()

    def test_smtp_backend_plain_send(self):
        from pyvelm.mail import SmtpBackend

        conn = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("pyvelm.mail.smtplib.SMTP", return_value=ctx):
            SmtpBackend(host="smtp.test", from_addr="noreply@test").send(
                to="to@test",
                subject="Subj",
                body="Body",
                cc="cc@test",
                bcc="bcc@test",
                reply_to="reply@test",
            )
        conn.send_message.assert_called_once()

    def test_smtp_backend_html_login_and_attachments(self):
        from pyvelm.mail import SmtpBackend

        conn = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        payloads = [
            (b"pdf-bytes", "doc.pdf", "application/pdf"),
            (None, "skip.bin", "application/octet-stream"),
            (b"raw", "data", "octetstream"),
        ]
        with (
            patch("pyvelm.mail.smtplib.SMTP", return_value=ctx),
            patch("pyvelm.mail._attachment_payload", side_effect=payloads),
        ):
            SmtpBackend(
                host="smtp.test",
                user="user",
                password="secret",
                use_tls=True,
            ).send(
                to="to@test",
                subject="",
                body="",
                body_html="<p>Hi</p>",
                attachments=[MagicMock(), MagicMock(), MagicMock()],
            )
        conn.starttls.assert_called_once()
        conn.login.assert_called_once_with("user", "secret")
        sent_msg = conn.send_message.call_args[0][0]
        self.assertIsInstance(sent_msg, EmailMessage)

    def test_smtp_requires_to_address(self):
        from pyvelm.mail import SmtpBackend

        with self.assertRaises(ValueError):
            SmtpBackend(host="x").send(to="", subject="s", body="b")


class AttachmentHelperTests(unittest.TestCase):
    def test_attachment_payload_fetch(self):
        from pyvelm.mail import _attachment_payload

        att = MagicMock()
        att.datas_fname = "upload.pdf"
        att.name = "file.bin"
        att.mimetype = "application/pdf"
        att.fetch_content.return_value = b"data"
        data, name, ctype = _attachment_payload(att)
        self.assertEqual(data, b"data")
        self.assertEqual(name, "upload.pdf")
        self.assertEqual(ctype, "application/pdf")

    def test_attachment_payload_empty_fetch_and_no_fetch(self):
        from pyvelm.mail import _attachment_payload

        att = MagicMock()
        att.fetch_content.return_value = b""
        data, name, _ = _attachment_payload(att)
        self.assertIsNone(data)
        self.assertTrue(name)

        plain = MagicMock(spec=["name", "mimetype"])
        plain.name = "orphan"
        plain.mimetype = None
        data2, name2, ctype2 = _attachment_payload(plain)
        self.assertIsNone(data2)
        self.assertEqual(name2, "orphan")
        self.assertEqual(ctype2, "application/octet-stream")

    def test_attachment_payload_fetch_failure(self):
        from pyvelm.mail import _attachment_payload

        att = MagicMock()
        att.fetch_content.side_effect = OSError("missing")
        data, _, _ = _attachment_payload(att)
        self.assertIsNone(data)

    def test_attachments_for_message(self):
        from pyvelm.mail import _attachments_for_message

        att = MagicMock()
        att_model = MagicMock()
        att_model.search.return_value = [att]
        env = MagicMock()
        env.registry = {"ir.attachment": object, "mail.message": object}
        env.__getitem__ = lambda _s, k: att_model
        result = _attachments_for_message(env, 42)
        self.assertEqual(result, [att])
        att_model.search.assert_called_once_with(
            [("res_model", "=", "mail.message"), ("res_id", "=", 42)]
        )

    def test_attachments_for_message_no_registry(self):
        from pyvelm.mail import _attachments_for_message

        env = MagicMock()
        env.registry = {}
        self.assertEqual(_attachments_for_message(env, 1), [])


class DispatchOutgoingTests(unittest.TestCase):
    def test_dispatch_without_mail_model(self):
        from pyvelm.mail import Message

        reg = Registry()
        with reg.activate():
            env = MagicMock()
            env.registry = {}
            self.assertEqual(Message.dispatch_outgoing(env), {"sent": 0, "failed": 0})

    def test_dispatch_passes_explicit_default_from(self):
        from pyvelm.mail import Message

        reg = _mail_registry()
        env = MagicMock()
        env.registry = reg
        env._acl_bypass = False
        env.transaction = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=None),
                __exit__=MagicMock(return_value=False),
            )
        )
        msg = MagicMock()
        msg.id = 1
        msg.recipient_email = "u@test"
        msg.subject = "S"
        msg.body = "B"
        msg.body_is_html = False
        msg.recipient_cc = None
        msg.recipient_bcc = None
        msg.reply_to = None
        Msg = MagicMock()
        Msg.search.return_value = [msg]
        env.__getitem__ = lambda _s, k: Msg

        class _Capture:
            last: dict = {}

            def send(self, **kwargs):
                _Capture.last = kwargs

        with (
            patch("pyvelm.mail._attachments_for_message", return_value=[]),
            patch.dict(os.environ, {"PYVELM_SMTP_FROM": "env-from@test"}, clear=False),
        ):
            Message.dispatch_outgoing(env, backend=_Capture())
        self.assertEqual(_Capture.last.get("from_addr"), "env-from@test")

    def test_dispatch_uses_load_backend_when_not_passed(self):
        from pyvelm.mail import Message

        reg = _mail_registry()
        env = MagicMock()
        env.registry = reg
        env._acl_bypass = False
        env.transaction = MagicMock(
            return_value=MagicMock(
                __enter__=MagicMock(return_value=None),
                __exit__=MagicMock(return_value=False),
            )
        )
        Msg = MagicMock()
        Msg.search.return_value = []
        env.__getitem__ = lambda _s, k: Msg
        from pyvelm.mail import DisabledBackend

        with patch(
            "pyvelm.mail._load_backend",
            return_value=(DisabledBackend(), "from@test"),
        ) as load:
            Message.dispatch_outgoing(env)
        load.assert_called_once()

    def test_dispatch_sends_and_marks_sent(self):
        from pyvelm.mail import DisabledBackend, Message

        reg = _mail_registry()
        with reg.activate():

            env = MagicMock()
            env.registry = reg
            env.uid = 1
            env._acl_bypass = False

            @contextmanager
            def _txn():
                yield

            env.transaction = _txn

            msg = MagicMock()
            msg.id = 1
            msg.recipient_email = "user@test"
            msg.subject = "Hello"
            msg.body = "Body"
            msg.body_is_html = False
            msg.recipient_cc = None
            msg.recipient_bcc = None
            msg.reply_to = None

            Msg = MagicMock()
            Msg.search.return_value = [msg]
            env.__getitem__ = lambda _s, k: Msg

            with (
                patch("pyvelm.mail._attachments_for_message", return_value=[]),
                self.assertLogs("pyvelm.mail", level="INFO"),
            ):
                stats = Message.dispatch_outgoing(
                    env, backend=DisabledBackend()
                )
            self.assertEqual(stats, {"sent": 1, "failed": 0})
            msg.write.assert_called()

    def test_dispatch_skips_blank_recipient(self):
        from pyvelm.mail import DisabledBackend, Message

        reg = _mail_registry()
        with reg.activate():

            env = MagicMock()
            env.registry = reg
            env._acl_bypass = False
            env.transaction = MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=None),
                    __exit__=MagicMock(return_value=False),
                )
            )
            msg = MagicMock()
            msg.recipient_email = ""
            Msg = MagicMock()
            Msg.search.return_value = [msg]
            env.__getitem__ = lambda _s, k: Msg
            stats = Message.dispatch_outgoing(env, backend=DisabledBackend())
            self.assertEqual(stats["sent"], 0)

    def test_dispatch_failure_marks_failed(self):
        from pyvelm.mail import Message

        reg = _mail_registry()
        with reg.activate():
            env = MagicMock()
            env.registry = reg
            env._acl_bypass = False
            env.transaction = MagicMock(
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=None),
                    __exit__=MagicMock(return_value=False),
                )
            )
            msg = MagicMock()
            msg.id = 2
            msg.recipient_email = "user@test"
            msg.subject = None
            msg.body = "x"
            msg.body_is_html = True
            msg.recipient_cc = None
            msg.recipient_bcc = None
            msg.reply_to = None
            Msg = MagicMock()
            Msg.search.return_value = [msg]
            env.__getitem__ = lambda _s, k: Msg

            class _Boom:
                def send(self, **_kwargs):
                    raise RuntimeError("smtp down")

            with (
                patch("pyvelm.mail._attachments_for_message", return_value=[]),
                self.assertLogs("pyvelm.mail", level="WARNING"),
            ):
                stats = Message.dispatch_outgoing(env, backend=_Boom())
            self.assertEqual(stats, {"sent": 0, "failed": 1})


class MessageComputeTests(unittest.TestCase):
    def test_compute_display_name(self):
        from pyvelm.mail import Message

        reg = _mail_registry()
        with reg.activate():
            long_body = "x" * 80
            r1 = MagicMock(body=long_body, id=1)
            r2 = MagicMock(body="", id=2)
            Message._compute_display_name([r1, r2])
            self.assertEqual(r1.display_name, long_body[:60])
            self.assertEqual(r2.display_name, "mail.message #2")


class MailThreadTests(unittest.TestCase):
    def test_message_post_creates_log(self):
        reg, Partner = _thread_registry(with_attachment=True)
        env, msg_model, att_row1, att_row2, *_rest = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 5)
        msg = partner.message_post("Hello", subtype="note", attachment_ids=[1, 2])
        self.assertEqual(msg.body, "Hello")
        msg_model.create.assert_called_once()
        call_vals = msg_model.create.call_args[0][0]
        self.assertEqual(call_vals["model"], "test.mail.partner")
        self.assertEqual(call_vals["res_id"], 5)
        self.assertEqual(call_vals["subtype"], "note")
        self.assertEqual(call_vals["author_id"], 1)
        att_row1.write.assert_called_once_with(
            {"res_model": "mail.message", "res_id": msg.id}
        )
        att_row2.write.assert_called_once_with(
            {"res_model": "mail.message", "res_id": msg.id}
        )

    def test_message_post_without_users_registry(self):
        reg, Partner = _thread_registry(with_attachment=True)
        env, msg_model, *_rest = _mock_thread_env(reg, with_users=False)
        partner = _partner(reg, Partner, env, 1)
        partner.message_post("Hi")
        vals = msg_model.create.call_args[0][0]
        self.assertNotIn("author_id", vals)

    def test_message_post_requires_mail_message(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Partner(MailThread, BaseModel):
                _name = "test.mail.lonely"
                name = Char()

        env = MagicMock()
        env.registry = reg
        partner = Partner(env, (1,))
        with self.assertRaises(RuntimeError):
            partner.message_post("x")

    def test_notify_queues_outgoing(self):
        reg, Partner = _thread_registry(with_attachment=True)
        env, msg_model, att_row1, att_row2, *_ = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 7)
        msg = partner.notify(
            "Body text",
            recipient_email="to@test",
            subject="Subj",
            cc="cc@test",
            bcc="bcc@test",
            reply_to="reply@test",
            body_is_html=True,
            subtype="alert",
            attachment_ids=[2],
        )
        vals = msg_model.create.call_args[0][0]
        self.assertEqual(vals["recipient_email"], "to@test")
        self.assertEqual(vals["state"], "outgoing")
        self.assertTrue(vals["body_is_html"])
        self.assertEqual(vals["subtype"], "alert")
        att_row1.write.assert_called_once()
        att_row2.write.assert_called_once()

    def test_notify_default_subject_from_body(self):
        reg, Partner = _thread_registry()
        env, msg_model, *_ = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 3)
        partner.notify("Short body", recipient_email="a@b.c")
        vals = msg_model.create.call_args[0][0]
        self.assertEqual(vals["subject"], "Short body")

    def test_notify_requires_mail_message(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Partner(MailThread, BaseModel):
                _name = "test.mail.notify.lonely"
                name = Char()

        env = MagicMock()
        env.registry = reg
        partner = Partner(env, (1,))
        with self.assertRaises(RuntimeError):
            partner.notify("b", recipient_email="a@test")

    def test_send_mail_delegates_to_template_object(self):
        reg, Partner = _thread_registry(with_template=True)
        env, _msg, _a1, _a2, _tpl_model, tpl_rec, _created = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 1)
        tpl = MagicMock()
        tpl.send_mail.return_value = MagicMock(id=50)
        out = partner.send_mail(
            tpl,
            to="a@test",
            cc="cc@test",
            bcc="bcc@test",
            reply_to="r@test",
            extra={"k": 1},
            attachment_ids=[3],
        )
        tpl.send_mail.assert_called_once()
        self.assertEqual(out.id, 50)

    def test_send_mail_browses_template_id(self):
        reg, Partner = _thread_registry(with_template=True)
        env, _msg, _a1, _a2, tpl_model, tpl_rec, _created = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 2)
        partner.send_mail(3, to="x@y.z")
        tpl_model.browse.assert_called_once_with(3)
        tpl_rec.send_mail.assert_called_once()

    def test_send_mail_unknown_template_raises(self):
        reg, Partner = _thread_registry(with_template=True)
        env, _msg, _a1, _a2, tpl_model, tpl_rec, _created = _mock_thread_env(reg)
        empty = MagicMock()
        empty._ids = ()
        tpl_model.browse.return_value = empty
        partner = _partner(reg, Partner, env, 1)
        with self.assertRaises(ValueError):
            partner.send_mail(999, to="a@b.c")

    def test_send_mail_without_template_model(self):
        reg, Partner = _thread_registry()
        env, *_rest = _mock_thread_env(reg, with_template=False)
        partner = _partner(reg, Partner, env, 1)
        with self.assertRaises(RuntimeError):
            partner.send_mail(1, to="a@b.c")

    def test_send_rendered_mail(self):
        reg, Partner = _thread_registry(with_template=True, with_attachment=True)
        env, msg_model, att_row1, att_row2, *_ = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 4)
        msg = partner._send_rendered_mail(
            subject="Rendered",
            body_html="<p>Hi</p>",
            recipient_email="user@test",
            cc="cc@test",
            bcc="bcc@test",
            reply_to="reply@test",
            template_id=3,
            attachment_ids=[5],
        )
        vals = msg_model.create.call_args[0][0]
        self.assertTrue(vals["body_is_html"])
        self.assertEqual(vals["template_id"], 3)
        self.assertEqual(vals["subject"], "Rendered")
        self.assertEqual(vals["author_id"], 1)
        att_row1.write.assert_called_once()

    def test_send_rendered_mail_requires_mail_message(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Partner(MailThread, BaseModel):
                _name = "test.mail.render.lonely"
                name = Char()

        env = _ThreadEnv({Partner._name: Partner}, {}, uid=1)
        partner = _partner(reg, Partner, env, 1)
        with self.assertRaises(RuntimeError):
            partner._send_rendered_mail(
                subject="S",
                body_html="<p>x</p>",
                recipient_email="a@b.c",
            )

    def test_send_rendered_mail_without_template_in_registry(self):
        reg, Partner = _thread_registry()
        env, msg_model, *_rest = _mock_thread_env(reg, with_template=False)
        partner = _partner(reg, Partner, env, 1)
        msg = partner._send_rendered_mail(
            subject="S",
            body_html="<b>x</b>",
            recipient_email="a@b.c",
            template_id=99,
        )
        vals = msg_model.create.call_args[0][0]
        self.assertNotIn("template_id", vals)
        self.assertEqual(msg.body, "<b>x</b>")

    def test_message_ids_property(self):
        reg, Partner = _thread_registry()
        env, msg_model, *_rest = _mock_thread_env(reg)
        partner = _partner(reg, Partner, env, 8)
        self.assertEqual(partner.message_ids, [10, 11])
        msg_model.search.assert_called_with(
            [("model", "=", "test.mail.partner"), ("res_id", "=", 8)]
        )

    def test_message_ids_empty_when_mail_unloaded(self):
        from pyvelm.mail import MailThread

        reg = Registry()
        with reg.activate():

            class Partner(MailThread, BaseModel):
                _name = "test.mail.ids.lonely"
                name = Char()

        env = MagicMock()
        env.registry = reg
        partner = Partner(env, (1,))
        self.assertEqual(partner.message_ids, [])


class LinkAttachmentsTests(unittest.TestCase):
    def test_link_attachments_noop_cases(self):
        from pyvelm.mail import _link_attachments

        env = MagicMock()
        env.registry = {}
        _link_attachments(env, None, "mail.message", 1)
        _link_attachments(env, [1], "mail.message", 1)

    def test_link_attachments_writes_rows(self):
        from pyvelm.mail import _link_attachments

        reg = _thread_registry(with_attachment=True)[0]
        env, _msg, att_row1, att_row2, *_ = _mock_thread_env(reg)
        _link_attachments(env, [1, 2], "mail.message", 99)
        att_row1.write.assert_called_once()
        att_row2.write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
