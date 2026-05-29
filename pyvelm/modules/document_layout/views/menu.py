"""Sidebar entry for document layout configuration (under Settings → Organization)."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("document_layout")

MENUS: list[Menu] = [
    m.item(
        "document_layout.configure",
        "Layout & Print",
        parent=("admin", "settings.organization"),
        view="res_company_layout.list",
        sequence=30,
        policy="view_any",
    ),
]
