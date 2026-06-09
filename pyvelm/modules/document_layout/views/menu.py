"""Sidebar entry for document layout configuration (under Settings → Organization)."""

from pyvelm.builders import Menus, ViewsData

m = Menus("document_layout")

views_data = (
    ViewsData.make()
    .menus(
        m.item(
            "document_layout.configure",
            "Layout & Print",
            parent=("admin", "settings.organization"),
            view="res_company_layout.list",
            sequence=30,
            policy="view_any",
        ),
    )
)
