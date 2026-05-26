"""Sidebar menu entries owned by the admin module.

Defines the Settings / Security / Workflows groups and the leaf
entries that link to admin-managed model lists.
"""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("admin")

MENUS: list[Menu] = [
    m.group("settings", "Settings", icon="cog-6-tooth", sequence=80),
    m.item(
        "settings.users",
        "Users",
        parent="settings",
        view="user.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "settings.groups",
        "Groups",
        parent="settings",
        view="group.list",
        sequence=20,
        policy="view_any",
    ),
    m.item(
        "settings.companies",
        "Companies",
        parent="settings",
        view="company.list",
        sequence=30,
        policy="view_any",
    ),
    m.item(
        "settings.currencies",
        "Currencies",
        parent="settings",
        view="currency.list",
        sequence=35,
        policy="view_any",
    ),
    m.group("security", "Security", icon="shield-check", sequence=90),
    m.item(
        "security.access",
        "Model access",
        parent="security",
        view="access.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "security.rules",
        "Record rules",
        parent="security",
        view="rule.list",
        sequence=20,
        policy="view_any",
    ),
    m.group("workflows", "Workflows", icon="bolt", sequence=100),
    m.item(
        "workflows.actions",
        "Server actions",
        parent="workflows",
        view="action.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "workflows.automation",
        "Automation",
        parent="workflows",
        view="automation.list",
        sequence=20,
        policy="view_any",
    ),
    m.item(
        "workflows.cron",
        "Cron jobs",
        parent="workflows",
        view="cron.list",
        sequence=30,
        policy="view_any",
    ),
    m.item(
        "workflows.messages",
        "Messages",
        parent="workflows",
        view="message.list",
        sequence=40,
        policy="view_any",
    ),
]
