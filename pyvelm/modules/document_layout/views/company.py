"""Document Layout configuration form (on `res.company`)."""

from typing import Any, cast

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View


def _w(name: str, widget: str):
    # `color`/`file_url` are real registered widgets but aren't in pyvelm's
    # WidgetHint literal — cast past the type checker (framework typing gap).
    return field(name, widget=cast(Any, widget))


VIEWS: list[View] = [
    list_view(
        "res_company_layout.list", "res.company",
        title="Document Layout",
        form_view="res_company_layout.form",
        fields=["name", "document_layout", "paper_format"],
    ),
    form_view(
        "res_company_layout.form", "res.company",
        sections=[
            section("layout", "Document Layout", [
                _w("document_designer", "design_button"),
                "document_layout", "paper_format", "google_font",
                _w("logo_url", "file_url"),
                _w("primary_color", "color"),
                _w("secondary_color", "color"),
            ]),
            section("contact", "Company Address (document header)", [
                "street", "city", "zip", "phone", "email", "website", "vat",
            ]),
            section("brand", "Branding", ["copyright_text"]),
        ],
    ),
]
