"""Sidebar menu entries owned by the base module.

Only the Dashboard and Apps roots live here — other navigation groups
(Settings, Security, Workflows) belong to the ``admin`` module, since
they front admin-owned models. Apps that ship their own pages
contribute their own MENUS through their data files (see crm,
partners, etc.).
"""

from pyvelm.builders import Menus, ViewsData

m = Menus("base")

# Root-level standalone items (no parent group, icon shown in sidebar).
views_data = (
    ViewsData.make()
    .menus(
        m.item(
            "dashboard",
            "Dashboard",
            href="/web/admin",
            icon="home",
            sequence=10,
        ),
        m.item(
            "apps",
            "Apps",
            href="/web/apps",
            icon="squares-2x2",
            sequence=100,
            model="res.users",
            policy="view_any",
        ),
    )
)
