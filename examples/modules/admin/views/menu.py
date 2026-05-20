"""Sidebar menu entries owned by the admin module.

Defines the Settings / Security / Workflows groups and the leaf
entries that link to admin-managed model lists.
"""

from pyvelm.builders import menu_group, menu_item
from pyvelm.types import Menu

_ICON_SETTINGS = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a6.759 6.759 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28z"/>'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>'
)

_ICON_SHIELD = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"/></svg>'
)

_ICON_WORKFLOW = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"/></svg>'
)


MENUS: list[Menu] = [
    # ----- Settings -----
    menu_group("settings", "Settings", icon=_ICON_SETTINGS, sequence=80),
    menu_item("settings.users",     "Users",     parent="admin.settings",
              href="/web/views/admin/user.list",    sequence=10),
    menu_item("settings.groups",    "Groups",    parent="admin.settings",
              href="/web/views/admin/group.list",   sequence=20),
    menu_item("settings.companies", "Companies", parent="admin.settings",
              href="/web/views/admin/company.list", sequence=30),
    menu_item("settings.tags",      "Tags",      parent="admin.settings",
              href="/web/views/admin/tag.list",     sequence=40),

    # ----- Security -----
    menu_group("security", "Security", icon=_ICON_SHIELD, sequence=90),
    menu_item("security.access", "Model access",  parent="admin.security",
              href="/web/views/admin/access.list", sequence=10),
    menu_item("security.rules",  "Record rules",  parent="admin.security",
              href="/web/views/admin/rule.list",   sequence=20),

    # ----- Workflows -----
    menu_group("workflows", "Workflows", icon=_ICON_WORKFLOW, sequence=100),
    menu_item("workflows.actions",    "Server actions", parent="admin.workflows",
              href="/web/views/admin/action.list",     sequence=10),
    menu_item("workflows.automation", "Automation",     parent="admin.workflows",
              href="/web/views/admin/automation.list", sequence=20),
    menu_item("workflows.cron",       "Cron jobs",      parent="admin.workflows",
              href="/web/views/admin/cron.list",       sequence=30),
    menu_item("workflows.messages",   "Messages",       parent="admin.workflows",
              href="/web/views/admin/message.list",    sequence=40),
]
