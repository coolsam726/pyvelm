"""User lifecycle list + detail views."""

from pyvelm.builders import DetailView, Field, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("user_lifecycle.list")
        .model("ir.user.lifecycle")
        .title("User lifecycle")
        .columns(["created_at", "event", "user_id", "actor_id"])
        .detail_view("user_lifecycle.detail")
        .page_actions(
            [
                {
                    "label": "Export CSV",
                    "url": "/web/audit/lifecycle/export",
                    "method": "GET",
                    "perm": "read",
                },
            ]
        ),
        DetailView.make("user_lifecycle.detail")
        .model("ir.user.lifecycle")
        .title("Lifecycle event")
        .section(
            "event",
            "Event",
            [
                "created_at",
                "event",
                "user_id",
                "actor_id",
                Field.make("detail").widget("code"),
            ],
        ),
    )
)
