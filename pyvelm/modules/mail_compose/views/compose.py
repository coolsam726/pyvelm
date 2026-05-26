"""Views for ``mail.compose.message`` — the composer form + drafts list."""

from pyvelm.builders import (
    field,
    form_view,
    list_view,
    section,
)
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "mail_compose.list",
        "mail.compose.message",
        title="Compose drafts",
        fields=[
            "subject",
            "recipient_to",
            field("model", widget="model"),
            "res_id",
            "state",
        ],
        form_view="mail_compose.form",
    ),
    form_view(
        "mail_compose.form",
        "mail.compose.message",
        title="Compose email",
        cols=2,
        header_actions=[
            {
                "label": "Apply template",
                "url": "/web/mail/compose/{id}/apply-template",
                "method": "POST",
            },
            {
                "label": "Save as template",
                "url": "/web/mail/compose/{id}/save-as-template",
                "method": "POST",
                "confirm": "Save current subject + body as a reusable template?",
            },
            {
                "label": "Send",
                "url": "/web/mail/compose/{id}/send",
                "method": "POST",
                "confirm": "Send this email now?",
            },
        ],
        sections=[
            section(
                "context",
                "Context",
                [
                    field("template_id"),
                    "state",
                    field("model", widget="model"),
                    "res_id",
                ],
            ),
            section(
                "recipients",
                "Recipients",
                [
                    field("recipient_to", colspan="full"),
                    field("recipient_cc", colspan="full"),
                    field("recipient_bcc", colspan="full"),
                    "reply_to",
                ],
            ),
            section(
                "subject",
                "Subject",
                [field("subject", colspan="full")],
                cols=1,
            ),
            section("body", "Body", ["body_html"], cols=1),
            section(
                "attachments",
                "Attachments",
                [field("attachment_ids", widget="dialog")],
                cols=1,
            ),
            section("error", "Error", ["error"], cols=1),
        ],
    ),
]
