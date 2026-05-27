"""Sidebar entries owned by the crm module."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("crm")

MENUS: list[Menu] = [
    m.group("crm", "CRM", icon="chart-bar", sequence=30),
    m.group("crm.sales", "Pipeline", parent="crm", sequence=10),
    m.item(
        "crm.kanban",
        "Pipeline board",
        parent="crm.sales",
        view="lead.kanban",
        sequence=10,
    ),
    m.item("crm.leads", "All Leads", parent="crm.sales", view="lead.list", sequence=20),
    m.group("crm.analytics", "Analytics", parent="crm", sequence=20),
    m.item("crm.revenue", "Revenue", parent="crm.analytics", view="lead.graph", sequence=10),
    m.item("crm.pivot", "Pipeline pivot", parent="crm.analytics", view="lead.pivot", sequence=20),
]
