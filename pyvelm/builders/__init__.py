"""Fluent view and menu declaration builders (velmphp / Filament-style).

Preferred authoring::

    from pyvelm.builders import ViewsData, ListView, FormView, Field, Menus

    m = Menus("partners")
    views_data = (
        ViewsData.make()
        .views(
            ListView.make("partner.list")
            .model("res.partner")
            .columns(["name", Field.make("active").toggle()])
            .form_view("partner.form"),
            FormView.make("partner.form")
            .model("res.partner")
            .section("identity", "Identity", ["name", "code"]),
        )
        .menus(
            m.group("business", "Business", icon="home").children([
                m.item("business.partners", "Partners").view("partner.list"),
            ]),
        )
    )

Legacy function helpers (``list_view``, ``field``, ``section``, …) remain
available and delegate to the same fluent classes.
"""
from __future__ import annotations

from .action import Action, ActionForm
from .field import Field
from .layout import KanbanCard, Notebook, Page, Section
from .legacy import (
    card,
    chart_widget,
    dashboard_view,
    field,
    form_view,
    graph_view,
    inherit_view,
    kanban_view,
    link_widget,
    list_view,
    notebook,
    op_after,
    op_before,
    op_remove,
    op_replace,
    op_set,
    op_update,
    page,
    pivot_view,
    section,
    stat_widget,
    table_widget,
)
from .menus import (
    MenuBranch,
    MenuItem,
    Menus,
    flatten_menus,
    menu_group,
    menu_item,
    menu_ref,
    view_href,
    _resolve_menu_href,
    _resolve_menu_parent,
)
from .views import (
    ChartWidget,
    DashboardView,
    DetailView,
    FormView,
    GraphView,
    InheritView,
    KanbanView,
    LinkWidget,
    ListView,
    PivotView,
    StatWidget,
    TableWidget,
)
from .views_data import ViewsData

__all__ = [
    "Action",
    "ActionForm",
    "ChartWidget",
    "DashboardView",
    "DetailView",
    "Field",
    "FormView",
    "GraphView",
    "InheritView",
    "KanbanCard",
    "KanbanView",
    "LinkWidget",
    "ListView",
    "MenuBranch",
    "MenuItem",
    "Menus",
    "Notebook",
    "Page",
    "PivotView",
    "Section",
    "StatWidget",
    "TableWidget",
    "ViewsData",
    "card",
    "chart_widget",
    "dashboard_view",
    "field",
    "flatten_menus",
    "form_view",
    "graph_view",
    "inherit_view",
    "kanban_view",
    "link_widget",
    "list_view",
    "menu_group",
    "menu_item",
    "menu_ref",
    "notebook",
    "op_after",
    "op_before",
    "op_remove",
    "op_replace",
    "op_set",
    "op_update",
    "page",
    "pivot_view",
    "section",
    "stat_widget",
    "table_widget",
    "view_href",
    "_resolve_menu_href",
    "_resolve_menu_parent",
]
