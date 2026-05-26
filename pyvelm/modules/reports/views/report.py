"""Views for the reports module."""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "report.list",
        "ir.report",
        title="Reports",
        fields=["name", "root_model", field("active", widget="toggle"), "row_limit"],
        create_href="/web/reports/build",
        record_href="/web/reports/{id}/build",
    ),
    form_view(
        "report.form",
        "ir.report",
        header_actions=[
            {
                "label": "Design report",
                "url": "/web/reports/{id}/build",
                "method": "GET",
                "perm": "write",
            },
            {
                "label": "Run report",
                "url": "/web/reports/{id}/run",
                "method": "GET",
                "perm": "write",
            },
        ],
        sections=[
            section("main", "Report", [
                "name", "description", "root_model", "row_limit",
                field("output_format"),
                field("schedule_active", widget="toggle"),
            ]),
            section("access", "Access", ["group_ids"]),
            section("state", "State", [field("active", widget="toggle")]),
        ],
    ),
    list_view(
        "report_run.list",
        "ir.report.run",
        title="Report runs",
        fields=["report_id", "user_id", "row_count", "duration_ms", "format", "state"],
    ),
]
