"""View declarations for the ``partners`` module."""

from pyvelm.builders import (
    card,
    field,
    form_view,
    kanban_view,
    list_view,
    section,
)
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "partner.list", "res.partner",
        fields=["name", "code", "company_id", "age", "country_id", "active"],
        form_view="partner.form",
    ),

    form_view(
        "partner.form", "res.partner",
        sections=[
            section("identity", "Identity", ["name", "code"]),
            section("profile", "Profile",
                    ["age", "country_id", "company_id", "parent_id", "active"]),
            section("relations", "Relations", ["tag_ids", "child_ids"]),
        ],
    ),

    kanban_view(
        "partner.kanban", "res.partner",
        title="Partner Board",
        card=card(
            "name",
            subtitle="code",
            fields=["age", "country_id"],
            badges=[field("active", widget="toggle"), "tag_ids"],
        ),
        group_by="country_id",
        form_view="partner.form",
    ),
]
