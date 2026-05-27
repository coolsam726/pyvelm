"""Sidebar menu for Report Builder."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("reports")

MENUS: list[Menu] = [
    m.group("reports", "Reports", icon="document-chart-bar", sequence=75),
    m.group("reports.builder", "Builder", parent="reports", sequence=10),
    m.item(
        "reports.build",
        "Design a report",
        parent="reports.builder",
        href="/web/reports/build",
        sequence=5,
        model="ir.report",
        perm="create",
        policy="create",
    ),
    m.group("reports.library", "Catalog", parent="reports", sequence=20),
    m.item(
        "reports.catalog",
        "All reports",
        parent="reports.library",
        view="report.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "reports.runs",
        "Run history",
        parent="reports.library",
        view="report_run.list",
        sequence=20,
        policy="view_any",
    ),
]
