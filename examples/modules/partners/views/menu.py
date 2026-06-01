"""Sidebar entries owned by the partners module."""

from pyvelm.builders import Menus

m = Menus("partners")

MENUS = [
    m.group("business", "Business Logic", icon="square-3-stack-3d", sequence=50).children(
        [
            m.group("business.directory", "Directory", sequence=10).children(
                [
                    m.item(
                        "business.partners",
                        "Partners",
                        view="partner.list",
                        sequence=10,
                    ),
                ]
            ),
            m.item(
                "business.tags",
                "Tags",
                parent=("admin", "settings.reference"),
                view="tag.list",
                sequence=40,
            ),
        ]
    ),
]
