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
            section(
                "relations",
                "Relations",
                ["tag_ids", field("child_ids", widget="table")],
            ),
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

    # ---- res.tag ----
    # Moved here from admin: partners owns res.tag, so it owns the
    # views too. The Settings → Tags sidebar entry (see views/menu.py)
    # still parents under admin.settings via cross-module menu refs.
    list_view(
        "tag.list", "res.tag",
        # sequence opts into drag-reorder (handle column, forced sort).
        sequence="sequence",
        fields=["name"],
    ),
    form_view(
        "tag.form", "res.tag",
        sections=[section("main", "Tag", ["name"])],
    ),
]
