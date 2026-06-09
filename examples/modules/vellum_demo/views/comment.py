"""Views for ``vellum.demo.comment``."""

from pyvelm.builders import (
    Field,
    FormView,
    KanbanCard,
    KanbanView,
    ListView,
    ViewsData,
)

views_data = (
    ViewsData.make()
    .views(
        ListView.make("demo_comment.list")
        .model("vellum.demo.comment")
        .title("Comment")
        .columns(
            [
                "body",
                "note_id",
                Field.make("active").toggle(),
                "created_at",
                "updated_at",
            ]
        )
        .form_view("demo_comment.form"),
        FormView.make("demo_comment.form")
        .model("vellum.demo.comment")
        .section(
            "main",
            "Comment",
            [
                "note_id",
                Field.make("active").toggle(),
                Field.make("body").colspan("full"),
            ],
        )
        .section(
            "metadata",
            "Record info",
            [
                "created_at",
                "updated_at",
            ],
        ),
        KanbanView.make("demo_comment.kanban")
        .model("vellum.demo.comment")
        .card(
            KanbanCard.make("display_name").fields(
                [
                    "body",
                    "active",
                    "created_at",
                    "updated_at",
                ]
            )
        )
        # group_by="note_id",
        .sequence("sequence")
        .form_view("demo_comment.form"),
    )
)
