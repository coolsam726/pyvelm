"""Mail thread mixin, message model, and outgoing-mail dispatcher.

Three layers ship here:

1. ``mail.message`` — stores every message / log entry, keyed by
   (model, res_id) so messages associate with any record on any
   model.

2. ``MailThread`` — mixin: ``record.message_post(body)`` records
   a log entry without sending mail. ``record.notify(...)`` records
   an entry **and** queues it for SMTP delivery.

3. ``MailBackend`` + ``Message.dispatch_outgoing()`` — the queue
   walker the cron runner calls every tick. Picks up rows where
   ``recipient_email`` is set and ``state="outgoing"``, hands them
   to the configured backend, and transitions the row to ``sent``
   or ``failed`` (with the error captured).

Fields on mail.message
-----------------------
model              ``_name`` of the owning model (e.g. ``"res.partner"``).
res_id             Primary key of the owning record.
author_id          Many2one to res.users (nullable — system messages use None).
body               Text body (plain text or HTML; no enforcement here).
message_type       ``"comment"`` | ``"notification"`` | ``"email"`` (default ``"comment"``).
subtype            Free-form subtype label (e.g. ``"note"``, ``"done"``).
date               UTC naive datetime of posting.
recipient_email    Optional address; when set, the row is dispatched via SMTP.
subject            Subject line for outgoing email (falls back to body[:80]).
state              ``"outgoing"`` | ``"sent"`` | ``"failed"`` (default ``"outgoing"``).
error              Last dispatch failure (free-form string).

Mail backend selection
----------------------
``PYVELM_MAIL_BACKEND`` env var picks the implementation:

  - ``console`` (default) — logs to stdout. Safe for dev and tests.
  - ``disabled``         — silently drops every send. Use this in CI
                           or when you want the dispatcher to mark
                           messages as ``sent`` without actually
                           contacting an SMTP server.
  - ``smtp``             — talks SMTP to ``PYVELM_SMTP_HOST/PORT/...``.

SMTP env knobs:

    PYVELM_SMTP_HOST      Hostname (e.g. ``smtp.gmail.com``).
    PYVELM_SMTP_PORT      Port (default 587).
    PYVELM_SMTP_USER      Username, if the server requires auth.
    PYVELM_SMTP_PASSWORD  Password.
    PYVELM_SMTP_FROM      From-address. Required for the smtp backend.
    PYVELM_SMTP_USE_TLS   ``1`` (default) to STARTTLS, ``0`` to skip.
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol

from pyvelm import BaseModel, Char, Integer, Many2one, Text
from pyvelm.cron import _DatetimeField  # reuse the datetime field from cron

log = logging.getLogger("pyvelm.mail")


# ---- backend protocol --------------------------------------------------


class MailBackend(Protocol):
    """A pluggable transport for outgoing mail.

    Implementations raise on transient failures so the dispatcher can
    flip the row to ``state="failed"`` and surface the reason via
    ``error``. The protocol is intentionally narrow — one method —
    because every backend in this file collapses to "deliver this
    text to that address."
    """

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        from_addr: str | None = None,
    ) -> None: ...


class ConsoleBackend:
    """Logs the would-be send to stdout. Default backend in dev/CI.

    Useful for the smoke test + interactive demo because there's no
    SMTP server to stand up and the operator gets visible feedback
    that the dispatcher ran.
    """

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        from_addr: str | None = None,
    ) -> None:
        log.info(
            "[mail console] %s → %s | %s",
            from_addr or "<no-from>",
            to,
            subject or "(no subject)",
        )
        if body:
            log.info(
                "[mail console] body: %s", body if len(body) < 200 else body[:200] + "…"
            )


class DisabledBackend:
    """No-op. ``state`` rolls to ``sent`` without anything happening."""

    def send(self, **_kwargs) -> None:
        return None


class SmtpBackend:
    """RFC-5321 SMTP transport via the standard-library ``smtplib``.

    Config comes from the ``PYVELM_SMTP_*`` env vars (see module
    docstring). The backend opens a fresh connection for each call —
    fine at typical pyvelm cadences (one tick per minute). A future
    pooling refinement is on the table if mail volume grows.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        user: str | None = None,
        password: str | None = None,
        from_addr: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        from_addr: str | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject or "(no subject)"
        msg["To"] = to
        msg["From"] = from_addr or self.from_addr or "noreply@pyvelm"
        msg.set_content(body or "")
        with smtplib.SMTP(self.host, self.port) as conn:
            if self.use_tls:
                conn.starttls()
            if self.user and self.password:
                conn.login(self.user, self.password)
            conn.send_message(msg)


def _load_backend() -> tuple[MailBackend, str | None]:
    """Pick a backend from the environment.

    Returns ``(backend, default_from)`` — the second element is the
    ``PYVELM_SMTP_FROM`` value the dispatcher passes when the message
    didn't set its own from-address. ``None`` means "let the backend
    decide."
    """
    kind = (os.environ.get("PYVELM_MAIL_BACKEND") or "console").lower()
    if kind == "disabled":
        return DisabledBackend(), None
    if kind == "smtp":
        host = os.environ.get("PYVELM_SMTP_HOST")
        if not host:
            raise RuntimeError("PYVELM_MAIL_BACKEND=smtp requires PYVELM_SMTP_HOST")
        return (
            SmtpBackend(
                host=host,
                port=int(os.environ.get("PYVELM_SMTP_PORT", "587")),
                user=os.environ.get("PYVELM_SMTP_USER") or None,
                password=os.environ.get("PYVELM_SMTP_PASSWORD") or None,
                from_addr=os.environ.get("PYVELM_SMTP_FROM") or None,
                use_tls=os.environ.get("PYVELM_SMTP_USE_TLS", "1") != "0",
            ),
            os.environ.get("PYVELM_SMTP_FROM") or None,
        )
    # default: console
    return ConsoleBackend(), os.environ.get("PYVELM_SMTP_FROM") or None


# ---- model -------------------------------------------------------------


class Message(BaseModel):
    _name = "mail.message"

    model = Char()
    res_id = Integer()
    author_id = Many2one("res.users", ondelete="SET NULL")
    body = Text()
    message_type = Char(default="comment")  # comment / notification / email
    subtype = Char()
    date = _DatetimeField()

    # Outgoing-mail fields. Records without `recipient_email` stay
    # purely as log entries — the dispatcher never touches them.
    recipient_email = Char()
    subject = Char()
    state = Char(default="outgoing")  # outgoing / sent / failed
    error = Text()

    @property
    def display_name(self) -> str:
        self.ensure_one()
        return self.body[:60] if self.body else ""

    # ---- dispatcher -----------------------------------------------------

    @classmethod
    def dispatch_outgoing(
        cls, env, *, limit: int = 50, backend: MailBackend | None = None
    ) -> dict:
        """Drain the outgoing queue.

        Picks up to ``limit`` messages with ``state="outgoing"`` AND
        ``recipient_email IS NOT NULL``, hands each to ``backend``, and
        transitions the row to ``sent`` or ``failed`` (capturing the
        error). Returns ``{"sent": N, "failed": M}`` — useful for the
        cron action log and tests.

        Runs under ACL bypass: the dispatcher is system code, not a
        per-user action.
        """
        if "mail.message" not in env.registry:
            return {"sent": 0, "failed": 0}

        if backend is None:
            backend, default_from = _load_backend()
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
                # An empty-string recipient slipped past the !=-None
                # filter? Skip it — the row needs operator attention,
                # not a noisy dispatch attempt.
                if not msg.recipient_email:
                    continue
                subject = msg.subject or (msg.body or "(no subject)")[:80]
                try:
                    backend.send(
                        to=msg.recipient_email,
                        subject=subject,
                        body=msg.body or "",
                        from_addr=default_from,
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


def _link_attachments(
    env, attachment_ids: list[int] | None, res_model: str, res_id: int
) -> None:
    """Point each attachment row at (res_model, res_id).

    Used by ``MailThread.message_post`` / ``notify`` to re-home
    just-uploaded ``ir.attachment`` rows onto the freshly-created
    message. No-op when ``ir.attachment`` isn't loaded or the caller
    passed nothing.

    Silently skips ids that don't resolve — a missing attachment
    shouldn't fail the whole post."""
    if not attachment_ids:
        return
    if "ir.attachment" not in env.registry:
        return
    Att = env["ir.attachment"]
    rows = Att.browse(tuple(attachment_ids))
    for rec in rows:
        rec.write({"res_model": res_model, "res_id": res_id})


class MailThread:
    """Mixin that adds chatter / message-thread capability to any model.

    Must appear before `BaseModel` in the MRO so that its `__init__`
    still delegates upward correctly:

        class MyModel(MailThread, BaseModel):
            _name = "my.model"
    """

    def message_post(
        self,
        body: str,
        *,
        message_type: str = "comment",
        subtype: str = "",
        attachment_ids: list[int] | None = None,
    ) -> "Message":
        """Create a new ``mail.message`` log entry for this record.

        The returned message is NOT queued for SMTP — it's just a log
        line. Use ``notify()`` when you want both a log entry and an
        outgoing email.

        ``attachment_ids`` re-points existing ``ir.attachment`` rows
        at the new message (``res_model = "mail.message"``, ``res_id =
        msg.id``). Callers upload the bytes first (via
        ``POST /api/attachment/upload``) and pass the resulting ids in.
        """
        self.ensure_one()
        if "mail.message" not in self.env.registry:
            raise RuntimeError(
                "mail.message model is not loaded — make sure the base "
                "module (which defines it) is installed."
            )
        vals: dict = {
            "model": self._name,
            "res_id": self.id,
            "body": body,
            "message_type": message_type,
            "date": datetime.utcnow(),
        }
        if subtype:
            vals["subtype"] = subtype
        if self.env.uid is not None and "res.users" in self.env.registry:
            vals["author_id"] = self.env.uid
        msg = self.env["mail.message"].create(vals)
        _link_attachments(self.env, attachment_ids, "mail.message", msg.id)
        return msg

    def notify(
        self,
        body: str,
        *,
        recipient_email: str,
        subject: str = "",
        message_type: str = "email",
        subtype: str = "",
        attachment_ids: list[int] | None = None,
    ) -> "Message":
        """Log a message AND queue it for SMTP delivery.

        Same shape as ``message_post`` but additionally sets the
        ``recipient_email`` and ``subject`` fields so the next
        dispatcher tick picks the row up.

        ``attachment_ids`` works the same way as in ``message_post`` —
        the SMTP backend currently doesn't add the bytes to the
        outgoing mail (that's a follow-up), but the linkage is
        recorded so the chatter UI can render them.
        """
        self.ensure_one()
        if "mail.message" not in self.env.registry:
            raise RuntimeError("mail.message model is not loaded")
        vals: dict = {
            "model": self._name,
            "res_id": self.id,
            "body": body,
            "message_type": message_type,
            "date": datetime.utcnow(),
            "recipient_email": recipient_email,
            "subject": subject or (body[:80] if body else ""),
            "state": "outgoing",
        }
        if subtype:
            vals["subtype"] = subtype
        if self.env.uid is not None and "res.users" in self.env.registry:
            vals["author_id"] = self.env.uid
        msg = self.env["mail.message"].create(vals)
        _link_attachments(self.env, attachment_ids, "mail.message", msg.id)
        return msg

    @property
    def message_ids(self) -> list[int]:
        """Return the ids of all messages attached to this record."""
        self.ensure_one()
        if "mail.message" not in self.env.registry:
            return []
        msgs = self.env["mail.message"].search(
            [
                ("model", "=", self._name),
                ("res_id", "=", self.id),
            ]
        )
        return msgs.ids
