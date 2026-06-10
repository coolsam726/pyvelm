"""Login history list + detail views."""

from pyvelm.builders import DetailView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("login_log.list")
        .model("ir.login.log")
        .title("Login history")
        .columns(
            [
                "created_at",
                "event",
                "user_id",
                "email",
                "ip_address",
                "session_lifetime_minutes",
            ]
        )
        .detail_view("login_log.detail")
        .page_actions(
            [
                {
                    "label": "Export CSV",
                    "url": "/web/audit/logins/export",
                    "method": "GET",
                    "perm": "read",
                },
            ]
        ),
        DetailView.make("login_log.detail")
        .model("ir.login.log")
        .title("Login event")
        .section(
            "event",
            "Event",
            [
                "created_at",
                "event",
                "user_id",
                "email",
                "ip_address",
                "user_agent",
                "session_id",
                "session_lifetime_minutes",
            ],
        ),
    )
)
