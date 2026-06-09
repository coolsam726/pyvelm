"""Sidebar menu entries owned by the admin module.

Defines the Settings / Security / Workflows apps and nested sections.
Level-2 groups are subsections; list/form links live at level 3 so the
apps layout top bar stays compact (see ``docs/navigation.md``).
"""

from pyvelm.builders import Menus, ViewsData

m = Menus("admin")

views_data = (
    ViewsData.make()
    .menus(
        m.group("settings", "Settings", icon="cog-6-tooth", sequence=80).children(
            [
                m.group("settings.organization", "Organization", sequence=10).children(
                    [
                        m.item(
                            "settings.companies",
                            "Companies",
                            view="company.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "settings.currencies",
                            "Currencies",
                            view="currency.list",
                            sequence=20,
                            policy="view_any",
                        ),
                    ]
                ),
                m.group("settings.access", "Users & access", sequence=20).children(
                    [
                        m.item(
                            "settings.users",
                            "Users",
                            view="user.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "settings.groups",
                            "Groups",
                            view="group.list",
                            sequence=20,
                            policy="view_any",
                        ),
                    ]
                ),
                m.group(
                    "settings.reference", "Reference data", sequence=30
                ),
            ]
        ),
        m.group("security", "Security", icon="shield-check", sequence=90).children(
            [
                m.group("security.permissions", "Permissions", sequence=10).children(
                    [
                        m.item(
                            "security.access",
                            "Model access",
                            view="access.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "security.rules",
                            "Record rules",
                            view="rule.list",
                            sequence=20,
                            policy="view_any",
                        ),
                    ]
                ),
            ]
        ),
        m.group("workflows", "Workflows", icon="bolt", sequence=100).children(
            [
                m.group("workflows.operations", "Operations", sequence=10).children(
                    [
                        m.item(
                            "workflows.instances",
                            "Instances",
                            view="workflow_instance.list",
                            view_module="workflow",
                            sequence=20,
                            policy="view_any",
                        ),
                        m.item(
                            "workflows.approvals",
                            "Approvals",
                            view="workflow_approval.list",
                            view_module="workflow",
                            sequence=30,
                            policy="view_any",
                        ),
                        m.item(
                            "workflows.tasks",
                            "Tasks",
                            view="workflow_task.list",
                            view_module="workflow",
                            sequence=40,
                            policy="view_any",
                        ),
                    ]
                ),
                m.group(
                    "workflows.configuration", "Configuration", sequence=20
                ).children(
                    [
                        m.item(
                            "workflows.actions",
                            "Server actions",
                            view="action.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "workflows.automation",
                            "Automation",
                            view="automation.list",
                            sequence=20,
                            policy="view_any",
                        ),
                        m.item(
                            "workflows.cron",
                            "Cron jobs",
                            view="cron.list",
                            sequence=30,
                            policy="view_any",
                        ),
                    ]
                ),
                m.group("workflows.messaging", "Messaging", sequence=30).children(
                    [
                        m.item(
                            "workflows.mail_templates",
                            "Email templates",
                            view="mail_template.list",
                            sequence=10,
                            policy="view_any",
                        ),
                        m.item(
                            "workflows.messages",
                            "Messages",
                            view="message.list",
                            sequence=20,
                            policy="view_any",
                        ),
                    ]
                ),
            ]
        ),
    )
)
