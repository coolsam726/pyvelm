"""Document Layout configuration form (on `res.company`)."""

from typing import Any, cast

from pyvelm.builders import Field, FormView, ListView, ViewsData


def _w(name: str, widget: str):
    # `color`/`file_url` are real registered widgets but aren't in pyvelm's
    # WidgetHint literal — cast past the type checker (framework typing gap).
    return Field.make(name).widget(cast(Any, widget))


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
                _w("document_designer", "design_button"),
                "document_layout",
                "paper_format",
                "google_font",
                _w("logo_url", "file_url"),
                "document_logo_height",
                _w("primary_color", "color"),
                _w("secondary_color", "color"),
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
