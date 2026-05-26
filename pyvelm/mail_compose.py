"""``mail.compose.message`` — front-end record for the email composer.

Each row is one in-progress (or sent) composition. The composer binds
to a target record (``model`` + ``res_id``) so templates render with
``object`` available, and so the auto-resolved "To" address can come
from common email-bearing fields on the bound record.

Lifecycle
---------
1. ``MailCompose.launch(env, model, res_id, template_id=None)`` creates a
   draft row, pre-fills "To" from the bound record (best-effort scan),
   and — when a ``template_id`` is supplied — renders the template into
   ``subject``/``body_html`` immediately.
2. The user edits the draft on the composer form (header actions:
   **Apply template**, **Save as template**, **Send**).
3. ``MailCompose.action_send()`` pushes a row to the ``mail.message``
   outgoing queue (cc/bcc/attachments included), transitions the
   composer to ``state="sent"``, and leaves the draft in place as an
   audit trail. The cron dispatcher then delivers via SMTP.
"""

from __future__ import annotations

from typing import Any

from pyvelm import (
    BaseModel,
    Char,
    Html,
    Integer,
    Many2many,
    Many2one,
    Text,
)


_EMAIL_FIELD_NAMES = (
    "email",
    "email_from",
    "email_to",
    "contact_email",
    "work_email",
    "login",  # res.users keeps emails in `login`
)

# Many2one paths walked for an indirect email (e.g. partner_id.email).
# Only one hop deep — deeper traversal needs explicit code for the
# host model.
_EMAIL_M2O_PATHS = (
    ("partner_id", "email"),
    ("user_id", "email"),
    ("user_id", "login"),
    ("author_id", "login"),
    ("contact_id", "email"),
)


class MailCompose(BaseModel):
    _name = "mail.compose.message"
    _rec_name = "subject"

    # ---- bound record (the composition's anchor) -----------------------
    model = Char(string="Target Model")
    res_id = Integer(string="Target Record")

    # ---- template (optional) -------------------------------------------
    template_id = Many2one("mail.template", string="Template")

    # ---- composed content ----------------------------------------------
    subject = Char(string="Subject")
    body_html = Html(string="Body")

    # ---- recipients ----------------------------------------------------
    # All three accept a single address or a comma-separated list.
    # ``recipient_to`` is nullable so freshly-launched drafts (where the
    # auto-resolver couldn't find an email on the bound record) save
    # cleanly; ``action_send`` is the authoritative gate that refuses
    # to dispatch an empty To.
    recipient_to = Text(string="To")
    recipient_cc = Text(string="Cc")
    recipient_bcc = Text(string="Bcc")
    reply_to = Char(string="Reply-To")

    # ---- attachments ---------------------------------------------------
    # The relation reuses the generic ``ir.attachment`` model. The SMTP
    # backend reads bytes via each attachment's ``fetch_content()``.
    attachment_ids = Many2many("ir.attachment", string="Attachments")

    # ---- lifecycle -----------------------------------------------------
    state = Char(default="draft", string="State")  # draft / sent / failed
    error = Text(string="Error")

    # ---- launch -------------------------------------------------------

    @classmethod
    def launch(
        cls,
        env,
        *,
        model: str | None = None,
        res_id: int | None = None,
        template_id: int | None = None,
        recipient_to: str = "",
    ):
        """Create a draft composer pre-filled for a target record.

        Returns the new ``mail.compose.message`` recordset (singleton).
        """
        vals: dict[str, Any] = {"state": "draft"}
        if model:
            vals["model"] = model
        if res_id:
            vals["res_id"] = int(res_id)

        to_value = (recipient_to or "").strip()
        if not to_value and model and res_id and model in env.registry:
            try:
                rec = env[model].browse(int(res_id))
                if rec._ids:
                    to_value = _resolve_default_to(rec)
            except Exception:  # noqa: BLE001
                to_value = ""
        vals["recipient_to"] = to_value or ""

        if template_id and "mail.template" in env.registry:
            tpl = env["mail.template"].browse(int(template_id))
            if tpl._ids:
                vals["template_id"] = tpl.id
                if model and res_id:
                    try:
                        rec = env[model].browse(int(res_id))
                        subject, body = tpl._render_for_record(rec)
                    except Exception:  # noqa: BLE001
                        subject, body = tpl.subject or "", tpl.body_html or ""
                    vals["subject"] = subject or ""
                    vals["body_html"] = body or ""
                else:
                    vals["subject"] = tpl.subject or ""
                    vals["body_html"] = tpl.body_html or ""

        return cls(env, ()).create(vals)

    # ---- actions -------------------------------------------------------

    def action_apply_template(self):
        """Re-render the selected template into ``subject``/``body_html``.

        Overwrites whatever the operator had typed — explicit "apply"
        click confirms the intent. No-op when no template is selected
        or the bound record can't be resolved.
        """
        self.ensure_one()
        if not self.template_id:
            return self
        tpl = self.template_id
        if not self.model or not self.res_id or self.model not in self.env.registry:
            self.write({
                "subject": tpl.subject or "",
                "body_html": tpl.body_html or "",
            })
            return self
        rec = self.env[self.model].browse(int(self.res_id))
        if not rec._ids:
            self.write({
                "subject": tpl.subject or "",
                "body_html": tpl.body_html or "",
            })
            return self
        subject, body = tpl._render_for_record(rec)
        self.write({"subject": subject or "", "body_html": body or ""})
        return self

    def action_send(self):
        """Queue the composer's content as an outgoing ``mail.message``.

        The bound record's ``MailThread._send_rendered_mail`` is used
        when available — that links the message into the record's
        chatter. Composers without a MailThread-bearing target fall back
        to creating the row directly on ``mail.message``.
        """
        self.ensure_one()
        if not (self.recipient_to or "").strip():
            raise ValueError("Recipient (To) is required")

        from pyvelm.mail import MailThread

        attachment_ids = [a.id for a in self.attachment_ids] if self.attachment_ids else None
        target = None
        if self.model and self.res_id and self.model in self.env.registry:
            Model = self.env.registry[self.model]
            if issubclass(Model, MailThread):
                rec = self.env[self.model].browse(int(self.res_id))
                if rec._ids:
                    target = rec

        try:
            if target is not None:
                target._send_rendered_mail(
                    subject=self.subject or "",
                    body_html=self.body_html or "",
                    recipient_email=str(self.recipient_to).strip(),
                    cc=(self.recipient_cc or None),
                    bcc=(self.recipient_bcc or None),
                    reply_to=(self.reply_to or None),
                    template_id=(self.template_id.id if self.template_id else None),
                    attachment_ids=attachment_ids,
                )
            else:
                Msg = self.env["mail.message"]
                from datetime import datetime
                vals = {
                    "model": self.model or "mail.compose.message",
                    "res_id": int(self.res_id or self.id),
                    "body": self.body_html or "",
                    "body_is_html": True,
                    "message_type": "email",
                    "date": datetime.utcnow(),
                    "recipient_email": str(self.recipient_to).strip(),
                    "recipient_cc": (self.recipient_cc or None),
                    "recipient_bcc": (self.recipient_bcc or None),
                    "reply_to": (self.reply_to or None),
                    "subject": self.subject or "",
                    "state": "outgoing",
                }
                if self.template_id:
                    vals["template_id"] = self.template_id.id
                if self.env.uid is not None and "res.users" in self.env.registry:
                    vals["author_id"] = self.env.uid
                msg = Msg.create(vals)
                if attachment_ids:
                    from pyvelm.mail import _link_attachments
                    _link_attachments(
                        self.env, attachment_ids, "mail.message", msg.id
                    )
        except Exception as exc:  # noqa: BLE001
            self.write({"state": "failed", "error": str(exc)})
            raise

        self.write({"state": "sent", "error": None})
        return self

    def action_save_as_template(self, *, name: str):
        """Persist this composer as a reusable ``mail.template``.

        Requires ``name`` (the new template's display name) and a bound
        ``model`` — templates target one model. Returns the created
        template recordset.
        """
        self.ensure_one()
        name = (name or "").strip()
        if not name:
            raise ValueError("Template name is required")
        if not self.model:
            raise ValueError("Composer must be bound to a model to save as template")
        if "mail.template" not in self.env.registry:
            raise RuntimeError("mail.template model is not loaded")
        Template = self.env["mail.template"]
        return Template.create({
            "name": name,
            "model": self.model,
            "subject": self.subject or "",
            "body_html": self.body_html or "",
            "active": True,
        })


def _resolve_default_to(record) -> str:
    """Best-effort: find an email-like value on the bound record.

    Walks direct fields first (``email``, ``email_from``, …) and then a
    short list of one-hop Many2one paths (``partner_id.email``,
    ``user_id.login``). Returns an empty string when nothing matches —
    callers leave the composer's "To" empty for the operator to fill in.
    """
    Model = type(record)
    fields = getattr(Model, "_fields", {})
    for fname in _EMAIL_FIELD_NAMES:
        if fname in fields:
            value = getattr(record, fname, None)
            if value:
                return str(value).strip()
    for rel, attr in _EMAIL_M2O_PATHS:
        if rel not in fields:
            continue
        try:
            related = getattr(record, rel)
        except Exception:  # noqa: BLE001
            continue
        if not related or not getattr(related, "_ids", ()):
            continue
        value = getattr(related, attr, None)
        if value:
            return str(value).strip()
    return ""
