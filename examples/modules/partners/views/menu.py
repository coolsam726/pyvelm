"""Sidebar entries owned by the partners module."""

from pyvelm.builders import menu_group, menu_item
from pyvelm.types import Menu

_ICON_GRID = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 '
    "01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 "
    "2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 "
    "6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 "
    "2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 "
    '2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z"/></svg>'
)


MENUS: list[Menu] = [
    menu_group("business", "Business Logic", icon=_ICON_GRID, sequence=50),
    menu_item(
        "business.partners",
        "Partners",
        parent="partners.business",
        href="/web/views/partners/partner.list",
        sequence=10,
    ),
    menu_item(
        "business.partner_board",
        label="Partner Board",
        parent="partners.business",
        href="/web/views/partners/partner.kanban",
        sequence=20,
    ),
    # Tags settings entry: lives here (not admin) because partners owns
    # res.tag. Hangs off admin.settings — admin still owns the group;
    # partners just contributes a leaf entry to it. Cross-module menu
    # parenting is supported by the ir.ui.menu sync layer.
    menu_item(
        "business.tags",
        label="Tags",
        parent="admin.settings",
        href="/web/views/partners/tag.list",
        sequence=40,
    ),
]
