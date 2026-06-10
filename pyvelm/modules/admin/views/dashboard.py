"""Declarative admin dashboard at ``/web/admin``.

Widgets are defined here and synced as ``ir.ui.view`` with
``view_type="dashboard"``. Modules can add their own dashboard views
and point menu entries at ``/web/views/<module>/<name>``.
"""

from pyvelm.builders import (
    ChartWidget,
    DashboardView,
    LinkWidget,
    StatWidget,
    TableWidget,
    ViewsData,
)

views_data = (
    ViewsData.make()
    .views(
        DashboardView.make("home")
        .title("Dashboard")
        .subtitle("Framework configuration and security.")
        .columns(4)
        .widgets(
            [
                StatWidget.make("active_users")
                .title("Active users")
                .model("res.users")
                .domain([("active", "=", True)])
                .href("/web/views/admin/user.list")
                .perm("write"),
                StatWidget.make("companies")
                .title("Companies")
                .model("res.company")
                .href("/web/views/admin/company.list")
                .perm("write"),
                StatWidget.make("groups")
                .title("Groups")
                .model("res.groups")
                .href("/web/views/admin/group.list")
                .colspan(1)
                .perm("write"),
                StatWidget.make("active_currencies")
                .title("Active currencies")
                .model("res.currency")
                .domain([("active", "=", True)])
                .href("/web/views/admin/currency.list")
                .colspan(1)
                .perm("write"),
                ChartWidget.make("users_by_status")
                .title("Users by company")
                .model("res.users")
                .groupby("company_id")
                .measure("__count")
                .chart("pie")
                .perm("write"),
                TableWidget.make("recent_users")
                .title("Recent users")
                .view("user.list")
                .limit(8)
                .colspan(2)
                .order("id DESC")
                .perm("write"),
                LinkWidget.make("groups")
                .title("Groups")
                .subtitle("res.groups")
                .description("Manage permission groups and their members.")
                .url("/web/views/admin/group.list")
                .perm("write"),
                LinkWidget.make("users")
                .title("Users")
                .subtitle("res.users")
                .description("Create and manage operator accounts.")
                .url("/web/views/admin/user.list")
                .perm("write"),
                LinkWidget.make("access")
                .title("Access Control")
                .subtitle("ir.model.access")
                .description("Grant CRUD permissions per model and group.")
                .url("/web/views/admin/access.list")
                .perm("write"),
                LinkWidget.make("rules")
                .title("Record Rules")
                .subtitle("ir.rule")
                .description("Define row-level security using domain filters.")
                .url("/web/views/admin/rule.list")
                .perm("write"),
                LinkWidget.make("companies_link")
                .title("Companies")
                .subtitle("res.company")
                .description("Manage companies and multi-tenant configuration.")
                .url("/web/views/admin/company.list")
                .perm("write"),
                LinkWidget.make("partners")
                .title("Partners")
                .subtitle("res.partner")
                .description("Browse and manage partners for the current company.")
                .url("/web/views/contacts/partner.list"),
            ]
        ),
    )
)
