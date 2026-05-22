"""Views for Vellum demo models (browse via examples/serve.py)."""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "demo_note.list",
        "vellum.demo.note",
        fields=["title", "score", "body"],
        form_view="demo_note.form",
    ),
    form_view(
        "demo_note.form",
        "vellum.demo.note",
        sections=[
            section("main", "Note", ["title", "body", "score"]),
            section(
                "comments",
                "Comments",
                [field("comment_ids", widget="table")],
            ),
        ],
    ),
    list_view(
        "demo_comment.list",
        "vellum.demo.comment",
        fields=["note_id", "body"],
        form_view="demo_comment.form",
    ),
    form_view(
        "demo_comment.form",
        "vellum.demo.comment",
        sections=[section("main", "Comment", ["note_id", "body"])],
    ),
    list_view(
        "demo_soft_note.list",
        "vellum.demo.soft_note",
        fields=["title", "deleted_at"],
        form_view="demo_soft_note.form",
    ),
    form_view(
        "demo_soft_note.form",
        "vellum.demo.soft_note",
        sections=[section("main", "Soft note", ["title", "deleted_at"])],
    ),
]
