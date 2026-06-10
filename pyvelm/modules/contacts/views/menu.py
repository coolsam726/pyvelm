"""Sidebar entries owned by the contacts module."""

from pyvelm.builders import Menus, ViewsData

m = Menus("contacts")

views_data = (
    ViewsData.make()
    .menus(
        m.group("directory", "Contacts", icon="user-group", sequence=40).children(
            [
                m.item(
                    "directory.partners",
                    "Partners",
                    view="partner.list",
                    sequence=10,
                ),
            ]
        ),
    )
)
