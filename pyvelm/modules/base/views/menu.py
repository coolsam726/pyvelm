"""Sidebar menu entries owned by the base module.

Only the Dashboard and Apps roots live here — other navigation groups
(Settings, Security, Workflows) belong to the ``admin`` module, since
they front admin-owned models. Apps that ship their own pages
contribute their own MENUS through their data files (see crm,
partners, etc.).
"""

from pyvelm.builders import menu_item
from pyvelm.types import Menu

# Root-level standalone items (no parent group, icon shown in sidebar).
MENUS: list[Menu] = [
    menu_item("dashboard", "Dashboard", href="/web/admin", icon="home", sequence=10),
    menu_item(
        "apps",
        "Apps",
        href="/web/apps",
        icon="squares-2x2",
        sequence=100,
        model="res.users",
        policy="view_any",
    ),
]
