"""Declarative admin dashboard at ``/web/admin``.

Widgets are defined here and synced as ``ir.ui.view`` with
``view_type="dashboard"``. Modules can add their own dashboard views
and point menu entries at ``/web/views/<module>/<name>``.
"""

from pyvelm.builders import (
    chart_widget,
    dashboard_view,
    link_widget,
    stat_widget,
    table_widget,
)
from pyvelm.types import View

VIEWS: list[View] = [
    dashboard_view(
        "home",
        title="Dashboard",
        subtitle="Framework configuration and security.",
        columns=3,
        widgets=[
            stat_widget(
                "active_users",
                title="Active users",
                model="res.users",
                domain=[("active", "=", True)],
                href="/web/views/admin/user.list",
            ),
            stat_widget(
                "companies",
                title="Companies",
                model="res.company",
                href="/web/views/admin/company.list",
            ),
            chart_widget(
                "users_by_status",
                title="Users by status",
                model="res.users",
                groupby="active",
                measure="__count",
                chart="pie",
            ),
            table_widget(
                "recent_users",
                title="Recent users",
                view="user.list",
                limit=8,
                order="id DESC",
            ),
            link_widget(
                "groups",
                title="Groups",
                subtitle="res.groups",
                description="Manage permission groups and their members.",
                url="/web/views/admin/group.list",
            ),
            link_widget(
                "users",
                title="Users",
                subtitle="res.users",
                description="Create and manage operator accounts.",
                url="/web/views/admin/user.list",
            ),
            link_widget(
                "access",
                title="Access Control",
                subtitle="ir.model.access",
                description="Grant CRUD permissions per model and group.",
                url="/web/views/admin/access.list",
            ),
            link_widget(
                "rules",
                title="Record Rules",
                subtitle="ir.rule",
                description="Define row-level security using domain filters.",
                url="/web/views/admin/rule.list",
            ),
            link_widget(
                "companies_link",
                title="Companies",
                subtitle="res.company",
                description="Manage companies and multi-tenant configuration.",
                url="/web/views/admin/company.list",
            ),
            link_widget(
                "partners",
                title="Partners",
                subtitle="res.partner",
                description="Browse and manage partners for the current company.",
                url="/web/views/partners/partner.list",
            ),
        ],
    ),
]
