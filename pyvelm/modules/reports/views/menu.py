"""Sidebar menu for Report Builder."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

_ICON = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>'
    '</svg>'
)

m = Menus("reports")

MENUS: list[Menu] = [
    m.group("reports", "Reports", icon=_ICON, sequence=75),
    m.item("reports.build", "Design a report", parent="reports", href="/web/reports/build", sequence=5),
    m.item("reports.catalog", "All reports", parent="reports", view="report.list", sequence=10),
    m.item("reports.runs", "Run history", parent="reports", view="report_run.list", sequence=20),
]
