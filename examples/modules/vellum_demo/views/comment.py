"""Views for ``vellum.demo.comment``."""

from pyvelm.builders import card, field, form_view, kanban_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "demo_comment.list",
        "vellum.demo.comment",
        title="Comment",
        fields=[
            "body",
            "note_id",
            field("active", widget="toggle"),
            "created_at",
            "updated_at",
        ],
        form_view="demo_comment.form",
    ),
    form_view(
        "demo_comment.form",
        "vellum.demo.comment",
        sections=[
            section(
                "main",
                "Comment",
                [
                    "body",
                    "note_id",
                    field("active", widget="toggle"),
                ],
            ),
            section(
                "metadata",
                "Record info",
                [
                    "created_at",
                    "updated_at",
                ],
            ),
        ],
    ),
    kanban_view(
        "demo_comment.kanban",
        "vellum.demo.comment",
        card=card(
            "display_name",
            fields=[
                "body",
                "active",
                "created_at",
                "updated_at",
            ],
        ),
        # group_by="note_id",
        sequence="sequence",
        form_view="demo_comment.form",
    ),
]
