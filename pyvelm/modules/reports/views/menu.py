"""Sidebar menu for Report Builder."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("reports")

MENUS: list[Menu] = [
    m.group("reports", "Reports", icon="document-chart-bar", sequence=75),
    m.item("reports.build", "Design a report", parent="reports", href="/web/reports/build", sequence=5),
    m.item("reports.catalog", "All reports", parent="reports", view="report.list", sequence=10),
    m.item("reports.runs", "Run history", parent="reports", view="report_run.list", sequence=20),
]
