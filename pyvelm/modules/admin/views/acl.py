"""View declarations for the admin module.

Provides list + form views for the four ACL models that live in base:
  - res.groups       (groups)
  - res.users        (users)
  - ir.model.access  (access control entries)
  - ir.rule          (record rules / row-level security)

These are just regular pyvelm views — the admin module ships no custom
Python models; it reuses the ones defined in base.
"""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        # ---- res.groups ----
        ListView.make("group.list").model("res.groups").columns(["name"]),
        FormView.make("group.form")
        .model("res.groups")
        .section("main", "Group", ["name"])
        .section("members", "Members", ["user_ids"]),
        # ---- res.users ----
        ListView.make("user.list")
        .model("res.users")
        .columns(["name", "login", Field.make("active").toggle()]),
        FormView.make("user.form")
        .model("res.users")
        # Reset password swaps the form shell with the reset-
        # password sub-page; saving there bounces back to the
        # user record. Method=GET so the link reads as plain
        # navigation, and the endpoint guards on
        # res.users.write at the ORM level.
        .header_actions(
            [
                {
                    "label": "Reset password",
                    "url": "/web/users/{id}/reset-password",
                    "method": "GET",
                    "perm": "write",
                },
            ]
        )
        .section(
            "profile",
            "Profile",
            [
                Field.make("avatar_url").widget("image"),
            ],
        )
        .section(
            "identity",
            "Identity",
            [
                "name",
                "login",
                Field.make("active").toggle(),
                Field.make("company_id").widget("company"),
            ],
        )
        .section("groups", "Groups", ["group_ids"]),
        # ---- ir.model.access ----
        ListView.make("access.list")
        .model("ir.model.access")
        .title("Model Access")
        .columns(
            [
                "name",
                "model",
                "group_id",
                Field.make("perm_read").toggle(),
                Field.make("perm_write").toggle(),
                Field.make("perm_create").toggle(),
                Field.make("perm_unlink").toggle(),
            ]
        ),
        FormView.make("access.form")
        .model("ir.model.access")
        .section("main", "Access Rule", ["name", "model", "group_id"])
        .section(
            "permissions",
            "Permissions",
            [
                Field.make("perm_read").toggle(),
                Field.make("perm_write").toggle(),
                Field.make("perm_create").toggle(),
                Field.make("perm_unlink").toggle(),
            ],
        ),
        # ---- ir.rule ----
        ListView.make("rule.list")
        .model("ir.rule")
        .columns(
            [
                "name",
                "model",
                "group_id",
                Field.make("perm_read").toggle(),
                Field.make("perm_write").toggle(),
                Field.make("perm_create").toggle(),
                Field.make("perm_unlink").toggle(),
            ]
        ),
        FormView.make("rule.form")
        .model("ir.rule")
        .section("main", "Record Rule", ["name", "model", "group_id", "domain"])
        .section(
            "permissions",
            "Applies On",
            [
                Field.make("perm_read").toggle(),
                Field.make("perm_write").toggle(),
                Field.make("perm_create").toggle(),
                Field.make("perm_unlink").toggle(),
            ],
        ),
        # ---- res.company ----
        ListView.make("company.list")
        .model("res.company")
        .columns(
            [
                "name",
                "app_name",
                "currency_id",
                "timezone",
                "primary_color",
                Field.make("active").toggle(),
            ]
        ),
        FormView.make("company.form")
        .model("res.company")
        .section(
            "main",
            "Company",
            [
                "name",
                "currency_id",
                "timezone",
                Field.make("active").toggle(),
            ],
        )
        .section(
            "branding",
            "Branding & white-label",
            [
                "app_name",
                "app_tagline",
                Field.make("logo_url").widget("file_url"),
                Field.make("logo_url_dark").widget("file_url"),
                "header_logo_height",
                Field.make("show_header_brand_text").toggle(),
                Field.make("favicon_url").widget("file_url"),
                Field.make("primary_color").widget("color"),
                "font_family",
                "copyright_text",
                "support_email",
                "support_url",
                Field.make("show_powered_by").toggle(),
                "menu_layout",
            ],
        ),
        # ---- res.currency ----
        ListView.make("currency.list")
        .model("res.currency")
        .columns(
            [
                "code",
                "name",
                "symbol",
                "rounding",
                Field.make("active").toggle(),
            ]
        ),
        FormView.make("currency.form")
        .model("res.currency")
        .section(
            "main",
            "Currency",
            [
                "code",
                "name",
                "symbol",
                "rounding",
                Field.make("active").toggle(),
            ],
        )
        .section("rates", "Exchange rates", [Field.make("rate_ids").widget("table")]),
        # ---- res.currency.rate ----
        ListView.make("currency.rate.list")
        .model("res.currency.rate")
        .columns(["currency_id", "date", "rate"]),
        FormView.make("currency.rate.form")
        .model("res.currency.rate")
        .section("main", "Rate", ["currency_id", "date", "rate"]),
        # ---- ir.actions.server ----
        ListView.make("action.list")
        .model("ir.actions.server")
        .title("Server Actions")
        .columns(["name", "model", "action_type"]),
        FormView.make("action.form")
        .model("ir.actions.server")
        .section("main", "Action", ["name", "model", "action_type"])
        .section("payload", "Payload", ["vals_json", "code"]),
        # ---- base.automation ----
        ListView.make("automation.list")
        .model("base.automation")
        .title("Automation Rules")
        .columns(
            [
                "name",
                "model",
                "trigger",
                "action_id",
                Field.make("active").toggle(),
            ]
        ),
        FormView.make("automation.form")
        .model("base.automation")
        .section(
            "main",
            "Automation",
            [
                "name",
                "model",
                "trigger",
                "action_id",
                Field.make("active").toggle(),
            ],
        ),
        # ---- ir.cron ----
        ListView.make("cron.list")
        .model("ir.cron")
        .title("Scheduled Jobs")
        .columns(
            [
                "name",
                "action_id",
                "interval_number",
                "interval_type",
                "lastcall",
                "nextcall",
                Field.make("active").toggle(),
            ]
        ),
        FormView.make("cron.form")
        .model("ir.cron")
        .header_actions(
            [
                {
                    "label": "Run Now",
                    "url": "/web/cron/{id}/run-now",
                    "method": "POST",
                    "confirm": "Run this job now?",
                    "perm": "write",
                },
            ]
        )
        .section(
            "main",
            "Job",
            ["name", "action_id", Field.make("active").toggle()],
        )
        .section(
            "schedule",
            "Schedule",
            ["interval_number", "interval_type", "nextcall", "lastcall"],
        ),
        # ---- mail.template ----
        ListView.make("mail_template.list")
        .model("mail.template")
        .title("Email templates")
        .columns(
            [
                "name",
                Field.make("model").widget("model"),
                "subject",
                Field.make("active").toggle(),
            ]
        ),
        FormView.make("mail_template.form")
        .model("mail.template")
        # 2-column form; body section drops to 1 column so the rich
        # editor uses the full width. `body_html` is an Html field, so
        # the renderer picks the HTML editor automatically — no
        # `widget="html"` needed.
        .cols(2)
        .section(
            "main",
            "Template",
            [
                "name",
                Field.make("model").widget("model"),
                Field.make("subject").colspan("full"),
                Field.make("active").toggle(),
            ],
        )
        .section("body", "HTML body", ["body_html"], cols=1),
        # ---- mail.message ----
        ListView.make("message.list")
        .model("mail.message")
        .title("Messages")
        .columns(
            [
                "date",
                "subject",
                "recipient_email",
                "state",
                "message_type",
            ]
        ),
        FormView.make("message.form")
        .model("mail.message")
        .section(
            "main",
            "Message",
            [
                "subject",
                "recipient_email",
                "date",
                "message_type",
                "state",
            ],
        )
        .section("body", "Body", ["body"])
        .section(
            "meta",
            "Meta",
            [
                "model",
                "res_id",
                "author_id",
                "template_id",
                "subtype",
                "error",
            ],
        ),
    )
)
