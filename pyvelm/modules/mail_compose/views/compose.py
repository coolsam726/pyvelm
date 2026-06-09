"""Views for ``mail.compose.message`` — the composer form + drafts list."""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("mail_compose.list")
        .model("mail.compose.message")
        .title("Compose drafts")
        .columns(
            [
                "subject",
                "recipient_to",
                Field.make("model").widget("model"),
                "res_id",
                "state",
            ]
        )
        .form_view("mail_compose.form"),
        FormView.make("mail_compose.form")
        .model("mail.compose.message")
        .title("Compose email")
        .cols(2)
        .header_actions(
            [
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
            ]
        )
        .section(
            "context",
            "Context",
            [
                Field.make("template_id"),
                "state",
                Field.make("model").widget("model"),
                "res_id",
            ],
        )
        .section(
            "recipients",
            "Recipients",
            [
                Field.make("recipient_to").colspan("full"),
                Field.make("recipient_cc").colspan("full"),
                Field.make("recipient_bcc").colspan("full"),
                "reply_to",
            ],
        )
        .section(
            "subject",
            "Subject",
            [Field.make("subject").colspan("full")],
            cols=1,
        )
        .section("body", "Body", ["body_html"], cols=1)
        .section(
            "attachments",
            "Attachments",
            [Field.make("attachment_ids").widget("dialog")],
            cols=1,
        )
        .section("error", "Error", ["error"], cols=1),
    )
)
