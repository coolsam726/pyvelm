"""Sidebar menu for Report Builder."""

from pyvelm.builders import Menus, ViewsData

m = Menus("reports")

views_data = (
    ViewsData.make()
    .menus(
        m.group("reports", "Reports", icon="document-chart-bar", sequence=75).children(
            [
                m.group("reports.builder", "Builder", sequence=10).children(
                    [
                        m.item(
                            "reports.build",
                            "Design a report",
                            href="/web/reports/build",
                            sequence=5,
                            model="ir.report",
                            perm="create",
                            policy="create",
                        ),
                    ]
                ),
                m.group("reports.library", "Catalog", sequence=20).children(
                    [
                        m.item(
                            "reports.catalog",
                            "All reports",
                            view="report.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "reports.runs",
                            "Run history",
                            view="report_run.list",
                            sequence=20,
                            policy="view_any",
                        ),
                    ]
                ),
            ]
        ),
    )
)
