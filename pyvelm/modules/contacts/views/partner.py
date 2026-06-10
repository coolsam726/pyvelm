"""View declarations for the ``contacts`` module."""

from pyvelm.builders import FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .columns(
            [
                "name",
                "code",
                "email",
                "phone",
                "company_id",
                "country_id",
                "active",
            ]
        )
        .form_view("partner.form"),
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code", "active"])
        .section(
            "contact",
            "Contact",
            ["email", "phone", "country_id", "company_id", "parent_id"],
        ),
    )
)
