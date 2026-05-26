"""Email templates (Odoo-style ``mail.template``).

Templates store a subject and HTML body with Jinja2 placeholders. Admins
edit them in Settings → Workflows → Email templates. Application code calls
``record.send_mail(template, to=...)`` or ``template.send_mail(record, to=...)``.

Template context (available in ``{{ ... }}``):

  object   — the business record (when ``model`` matches).
  user     — ``res.users`` for the current env uid (or empty recordset).
  company  — ``res.company`` from env context / user default.
  ctx      — optional extra dict passed to ``send_mail(..., ctx={})``.
"""

from __future__ import annotations

from typing import Any

from pyvelm import BaseModel, Boolean, Char, Text, depends

from .mail_template_render import (
    build_mail_template_context,
    render_mail_template_string,
)

__all__ = [
    "MailTemplate",
    "build_mail_template_context",
    "render_mail_template_string",
]


class MailTemplate(BaseModel):
    _name = "mail.template"
    _rec_name = "name"

    name = Char(required=True)
    model = Char(required=True)  # technical model name, e.g. res.partner
    subject = Char(required=True)
    body_html = Text(required=True)
    active = Boolean(default=True)

    @depends("name")
    def _compute_display_name(self):
        for r in self:
            r.display_name = r.name or f"mail.template #{r.id}"

    def _render_for_record(
        self, record, *, extra: dict[str, Any] | None = None
    ) -> tuple[str, str]:
        """Return ``(subject, body_html)`` for *record*."""
        self.ensure_one()
        if record._name != self.model:
            raise ValueError(
                f"Template {self.name!r} applies to {self.model!r}, "
                f"not {record._name!r}"
            )
        record.ensure_one()
        context = build_mail_template_context(
            self.env, model=self.model, record=record, extra=extra
        )
        subject = render_mail_template_string(self.subject or "", context)
        body = render_mail_template_string(self.body_html or "", context)
        return subject, body

    def render_preview(
        self, res_id: int | None = None, *, extra: dict[str, Any] | None = None
    ) -> dict[str, str]:
        """Render subject/body for admin preview (optional record id)."""
        self.ensure_one()
        if self.model not in self.env.registry:
            raise ValueError(f"Unknown model {self.model!r}")
        Model = self.env[self.model]
        if res_id:
            record = Model.browse(res_id)
            if not record._ids:
                raise ValueError(f"No {self.model} record with id={res_id}")
        else:
            record = Model.search([], limit=1)
            if not record._ids:
                record = Model(self.env, ())
        subject, body = self._render_for_record(record, extra=extra)
        return {"subject": subject, "body_html": body}

    def send_mail(
        self,
        record,
        *,
        to: str,
        extra: dict[str, Any] | None = None,
        attachment_ids: list[int] | None = None,
    ):
        """Render this template and queue outgoing mail on *record*."""
        self.ensure_one()
        if not self.active:
            raise ValueError(f"Template {self.name!r} is inactive")
        if not to or not str(to).strip():
            raise ValueError("Recipient email is required")
        record.ensure_one()
        if not hasattr(record, "_send_rendered_mail"):
            raise TypeError(
                f"{record._name} must inherit MailThread to send templated mail"
            )
        subject, body_html = self._render_for_record(record, extra=extra)
        return record._send_rendered_mail(
            subject=subject,
            body_html=body_html,
            recipient_email=str(to).strip(),
            template_id=self.id,
            attachment_ids=attachment_ids,
        )
