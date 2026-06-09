"""Sidebar entries owned by the crm module."""

from pyvelm.builders import Menus, ViewsData

m = Menus("crm")

views_data = (
    ViewsData.make()
    .menus(
        m.group("crm", "CRM", icon="chart-bar", sequence=30).children(
            [
                m.group("crm.sales", "Pipeline", sequence=10).children(
                    [
                        m.item(
                            "crm.kanban",
                            "Pipeline board",
                            view="lead.kanban",
                            sequence=10,
                        ),
                        m.item(
                            "crm.leads",
                            "All Leads",
                            view="lead.list",
                            sequence=20,
                        ),
                    ]
                ),
                m.group("crm.analytics", "Analytics", sequence=20).children(
                    [
                        m.item(
                            "crm.revenue",
                            "Revenue",
                            view="lead.graph",
                            sequence=10,
                        ),
                        m.item(
                            "crm.pivot",
                            "Pipeline pivot",
                            view="lead.pivot",
                            sequence=20,
                        ),
                    ]
                ),
            ]
        ),
    )
)
