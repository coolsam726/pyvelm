"""Views for the reports module."""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("report.list")
        .model("ir.report")
        .title("Reports")
        .columns(
            [
                "name",
                "root_model",
                Field.make("active").toggle(),
                "row_limit",
            ]
        )
        .create_href("/web/reports/build")
        .record_href("/web/reports/{id}/build"),
        FormView.make("report.form")
        .model("ir.report")
        .header_actions(
            [
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
            ]
        )
        .section(
            "main",
            "Report",
            [
                "name",
                "description",
                "root_model",
                "row_limit",
                Field.make("output_format"),
                Field.make("schedule_active").toggle(),
            ],
        )
        .section("access", "Access", ["group_ids"])
        .section("state", "State", [Field.make("active").toggle()]),
        ListView.make("report_run.list")
        .model("ir.report.run")
        .title("Report runs")
        .columns(
            [
                "report_id",
                "user_id",
                "row_count",
                "duration_ms",
                "format",
                "state",
            ]
        ),
    )
)
