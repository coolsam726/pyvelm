"""Views for Vellum demo models (browse via examples/serve.py)."""

from pyvelm.builders import Field, FormView, ListView, Page, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("demo_note.list")
        .model("vellum.demo.note")
        .columns(
            [
                "id",
                "title",
                "publish_on",
                "event_at",
                "score",
                "active",
                "created_at",
            ]
        )
        .form_view("demo_note.form"),
        FormView.make("demo_note.form")
        .model("vellum.demo.note")
        .section(
            "main",
            "Note",
            [
                "title",
                "body",
                "score",
                "publish_on",
                "event_at",
                "standup_at",
                "active",
            ],
        )
        .notebook(
            "extra",
            "",
            [
                Page.make("snippet", "Snippet").fields(["snippet"]),
                Page.make("comments", "Comments").fields(
                    [
                        Field.make("comment_ids")
                        .widget("dialog")
                        .set(
                            edit_toggle=True,
                            list_view="demo_comment.compact",
                            form_view="demo_comment.form",
                            columns=[
                                "body",
                                Field.make("active").toggle(),
                            ],
                        ),
                    ]
                ),
            ],
        )
        .section("metadata", "Record info", ["created_at", "updated_at"]),
        ListView.make("demo_comment.list")
        .model("vellum.demo.comment")
        .columns(["note_id", "body", "active", "created_at", "updated_at"])
        .form_view("demo_comment.form"),
        ListView.make("demo_comment.compact")
        .model("vellum.demo.comment")
        .columns(["body", "active"])
        .form_view("demo_comment.form"),
        FormView.make("demo_comment.form")
        .model("vellum.demo.comment")
        .section("main", "Comment", ["note_id", "body", "active"])
        .section("metadata", "Record info", ["created_at", "updated_at"]),
        ListView.make("demo_soft_note.list")
        .model("vellum.demo.soft_note")
        .columns(["title", "deleted_at", "active", "created_at", "updated_at"])
        .form_view("demo_soft_note.form"),
        FormView.make("demo_soft_note.form")
        .model("vellum.demo.soft_note")
        .section("main", "Soft note", ["title", "deleted_at", "active"])
        .section("metadata", "Record info", ["created_at", "updated_at"]),
    )
)
