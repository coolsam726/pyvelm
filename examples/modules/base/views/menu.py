"""Sidebar menu entries owned by the base module.

Only the Dashboard root lives here — other navigation groups
(Settings, Security, Workflows) belong to the `admin` module, since
they front admin-owned models. Apps that ship their own pages
contribute their own MENUS through their data files (see crm,
partners, etc.).
"""

_ICON_HOME = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M2.25 12l8.954-8.955a1.5 1.5 0 012.122 0l8.954 8.955M4.5 9.75v9.75a.75.75 0 '
    '00.75.75H9V15a1.5 1.5 0 011.5-1.5h3a1.5 1.5 0 011.5 1.5v5.25h3.75a.75.75 0 '
    '00.75-.75V9.75M8.25 21h7.5"/></svg>'
)


MENUS: list[dict] = [
    {
        "name": "dashboard",
        "label": "Dashboard",
        "icon": _ICON_HOME,
        "href": "/web/admin",
        "sequence": 10,
    },
]
