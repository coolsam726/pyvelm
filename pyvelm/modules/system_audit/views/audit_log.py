"""Audit log list + detail views."""

from pyvelm.builders import DetailView, Field, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("audit_log.list")
        .model("ir.audit.log")
        .title("Audit log")
        .columns(
            [
                "created_at",
                "name",
                "model",
                "res_id",
                "action",
                "user_id",
                "ip_address",
            ]
        )
        .detail_view("audit_log.detail")
        .page_actions(
            [
                {
                    "label": "Export CSV",
                    "url": "/web/audit/logs/export",
                    "method": "GET",
                    "perm": "read",
                },
            ]
        ),
        DetailView.make("audit_log.detail")
        .model("ir.audit.log")
        .title("Audit event")
        .section(
            "event",
            "Event",
            [
                "name",
                "model",
                "res_id",
                "action",
                "user_id",
                "company_id",
                "ip_address",
                "user_agent",
                "created_at",
            ],
        )
        .section(
            "changes",
            "Changes",
            [
                Field.make("old_values").widget("code"),
                Field.make("new_values").widget("code"),
            ],
            cols=1,
        ),
    )
)
