"""Sidebar entries owned by the crm module."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("crm")

MENUS: list[Menu] = [
    m.group("crm", "CRM", icon="chart-bar", sequence=30),
    m.item("crm.pipeline", "Pipeline", parent="crm", view="lead.kanban", sequence=10),
    m.item("crm.leads", "All Leads", parent="crm", view="lead.list", sequence=20),
    m.item("crm.revenue", "Revenue", parent="crm", view="lead.graph", sequence=30),
    m.item("crm.pivot", "Pipeline pivot", parent="crm", view="lead.pivot", sequence=40),
]
