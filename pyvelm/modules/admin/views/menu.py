"""Sidebar menu entries owned by the admin module.

Defines the Settings / Security / Workflows apps and nested sections.
Level-2 groups are subsections; list/form links live at level 3 so the
apps layout top bar stays compact (see ``docs/navigation.md``).
"""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("admin")

MENUS: list[Menu] = [
    m.group("settings", "Settings", icon="cog-6-tooth", sequence=80),
    m.group("settings.organization", "Organization", parent="settings", sequence=10),
    m.item(
        "settings.companies",
        "Companies",
        parent="settings.organization",
        view="company.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "settings.currencies",
        "Currencies",
        parent="settings.organization",
        view="currency.list",
        sequence=20,
        policy="view_any",
    ),
    m.group("settings.access", "Users & access", parent="settings", sequence=20),
    m.item(
        "settings.users",
        "Users",
        parent="settings.access",
        view="user.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "settings.groups",
        "Groups",
        parent="settings.access",
        view="group.list",
        sequence=20,
        policy="view_any",
    ),
    m.group("settings.reference", "Reference data", parent="settings", sequence=30),
    m.group("security", "Security", icon="shield-check", sequence=90),
    m.group("security.permissions", "Permissions", parent="security", sequence=10),
    m.item(
        "security.access",
        "Model access",
        parent="security.permissions",
        view="access.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "security.rules",
        "Record rules",
        parent="security.permissions",
        view="rule.list",
        sequence=20,
        policy="view_any",
    ),
    m.group("workflows", "Workflows", icon="bolt", sequence=100),
    m.group("workflows.operations", "Operations", parent="workflows", sequence=10),
    m.item(
        "workflows.instances",
        "Instances",
        parent="workflows.operations",
        view="workflow_instance.list",
        view_module="workflow",
        sequence=20,
        policy="view_any",
    ),
    m.item(
        "workflows.approvals",
        "Approvals",
        parent="workflows.operations",
        view="workflow_approval.list",
        view_module="workflow",
        sequence=30,
        policy="view_any",
    ),
    m.item(
        "workflows.tasks",
        "Tasks",
        parent="workflows.operations",
        view="workflow_task.list",
        view_module="workflow",
        sequence=40,
        policy="view_any",
    ),
    m.group("workflows.configuration", "Configuration", parent="workflows", sequence=20),
    m.item(
        "workflows.actions",
        "Server actions",
        parent="workflows.configuration",
        view="action.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "workflows.automation",
        "Automation",
        parent="workflows.configuration",
        view="automation.list",
        sequence=20,
        policy="view_any",
    ),
    m.item(
        "workflows.cron",
        "Cron jobs",
        parent="workflows.configuration",
        view="cron.list",
        sequence=30,
        policy="view_any",
    ),
    m.group("workflows.messaging", "Messaging", parent="workflows", sequence=30),
    m.item(
        "workflows.mail_templates",
        "Email templates",
        parent="workflows.messaging",
        view="mail_template.list",
        sequence=10,
        policy="view_any",
    ),
    m.item(
        "workflows.messages",
        "Messages",
        parent="workflows.messaging",
        view="message.list",
        sequence=20,
        policy="view_any",
    ),
]
