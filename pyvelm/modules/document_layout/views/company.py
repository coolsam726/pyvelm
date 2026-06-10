"""Document Layout configuration form (on `res.company`)."""

from typing import Any, cast

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("res_company_layout.list")
        .model("res.company")
        .title("Document Layout")
        .form_view("res_company_layout.form")
        .columns(["name", "document_layout", "paper_format"]),
        FormView.make("res_company_layout.form")
        .model("res.company")
        .section(
            "layout",
            "Document Layout",
            [
                Field.make("document_designer").widget(cast(Any, "design_button")),
                "document_layout",
                "paper_format",
                "google_font",
                Field.make("logo_url").widget("file_url"),
                "document_logo_height",
                Field.make("primary_color").widget("color"),
                Field.make("secondary_color").widget("color"),
            ],
        )
        .section(
            "contact",
            "Company Address (document header)",
            [
                "street",
                "city",
                "zip",
                "phone",
                "email",
                "website",
                "vat",
            ],
        )
        .section("brand", "Branding", ["copyright_text"]),
    )
)
