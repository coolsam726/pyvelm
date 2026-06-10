"""``mail.message`` model — stored chatter / outgoing-mail queue rows."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from pyvelm import Boolean, Char, Integer, Many2one, Text, depends, models
from pyvelm.fields import Datetime as _DatetimeField

if TYPE_CHECKING:
    from pyvelm.mail import MailBackend

log = logging.getLogger("pyvelm.mail")


class Message(models.Model):
    _name = "mail.message"
    _rec_name = "body"

    model = Char()
    res_id = Integer()
    author_id = Many2one("res.users", ondelete="SET NULL")
    body = Text()
    message_type = Char(default="comment")  # comment / notification / email
    subtype = Char()
    date = _DatetimeField()

    recipient_email = Char()
    recipient_cc = Text()
    recipient_bcc = Text()
    reply_to = Char()
    subject = Char()
    body_is_html = Boolean(default=False)
    template_id = Many2one("mail.template", ondelete="SET NULL")
    state = Char(default="outgoing")  # outgoing / sent / failed
    error = Text()

    @depends("body")
    def _compute_display_name(self):
        for r in self:
            body = r.body or ""
            r.display_name = body[:60] if body else f"mail.message #{r.id}"

    @classmethod
    def dispatch_outgoing(
        cls, env, *, limit: int = 50, backend: MailBackend | None = None
    ) -> dict:
        """Drain the outgoing queue."""
        if "mail.message" not in env.registry:
            return {"sent": 0, "failed": 0}

        import pyvelm.mail as mail_mod

        if backend is None:
            backend, default_from = mail_mod._load_backend()
        else:
            default_from = os.environ.get("PYVELM_SMTP_FROM") or None

        sent = 0
        failed = 0
        prev_bypass = env._acl_bypass
        env._acl_bypass = True
        try:
            Msg = env["mail.message"]
            pending = Msg.search(
                [
                    ("state", "=", "outgoing"),
                    ("recipient_email", "!=", None),
                ],
                limit=limit,
            )
            for msg in pending:
                if not msg.recipient_email:
                    continue
                subject = msg.subject or (msg.body or "(no subject)")[:80]
                body = msg.body or ""
                is_html = bool(msg.body_is_html)
                atts = mail_mod._attachments_for_message(env, msg.id)
                try:
                    backend.send(
                        to=msg.recipient_email,
                        subject=subject,
                        body="" if is_html else body,
                        body_html=body if is_html else None,
                        from_addr=default_from,
                        cc=msg.recipient_cc or None,
                        bcc=msg.recipient_bcc or None,
                        reply_to=msg.reply_to or None,
                        attachments=atts or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log.warning(
                        "mail dispatch failed for message %s: %s",
                        msg.id,
                        exc,
                    )
                    with env.transaction():
                        msg.write({"state": "failed", "error": str(exc)})
                    continue
                with env.transaction():
                    msg.write({"state": "sent", "error": None})
                sent += 1
        finally:
            env._acl_bypass = prev_bypass

        if sent or failed:
            log.info("mail dispatcher: sent=%d failed=%d", sent, failed)
        return {"sent": sent, "failed": failed}
