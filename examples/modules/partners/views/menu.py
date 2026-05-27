"""Sidebar entries owned by the partners module."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("partners")

MENUS: list[Menu] = [
    m.group("business", "Business Logic", icon="square-3-stack-3d", sequence=50),
    m.group("business.directory", "Directory", parent="business", sequence=10),
    m.item(
        "business.partners",
        "Partners",
        parent="business.directory",
        view="partner.list",
        sequence=10,
    ),
    m.item(
        "business.tags",
        "Tags",
        parent=("admin", "settings.reference"),
        view="tag.list",
        sequence=40,
    ),
]
