"""Backward-compatible function wrappers around fluent builders."""
from __future__ import annotations

from typing import Any

from pyvelm.types import (
    ArchKanbanCard,
    ArchNotebook,
    ArchPage,
    ArchSection,
    DashboardColspan,
    DashboardWidget,
    FieldRef,
    FieldRefLike,
    FormLayoutItem,
    FormView,
    GraphView,
    KanbanView,
    ListView,
    Operation,
    PivotView,
    TargetSegment,
    ViewInherit,
    ViewRef,
    WidgetHint,
)

from .field import Field as FieldBuilder
from .layout import KanbanCard, Notebook, Page, Section
from .views import (
    ChartWidgetBuilder,
    DashboardViewBuilder,
    FormViewBuilder,
    GraphViewBuilder,
    InheritViewBuilder,
    KanbanViewBuilder,
    LinkWidgetBuilder,
    ListViewBuilder,
    PivotViewBuilder,
    StatWidgetBuilder,
    TableWidgetBuilder,
)


def field(
    name: str,
    *,
    widget: WidgetHint | None = None,
    label: str | None = None,
    readonly: bool | None = None,
    required: bool | None = None,
    colspan: int | str | None = None,
    **extra: Any,
) -> FieldRef:
    b = FieldBuilder.make(name)
    if widget is not None:
        b.widget(widget)
    if label is not None:
        b.label(label)
    if readonly is not None:
        b.readonly(readonly)
    if required is not None:
        b.required(required)
    if colspan is not None:
        b.colspan(colspan)
    if extra:
        b.set(**extra)
    return b.to_dict()


def section(
    name: str,
    title: str,
    fields: list[FieldRefLike],
    *,
    cols: int | None = None,
) -> ArchSection:
    b = Section.make(name, title).fields(fields)
    if cols is not None:
        b.cols(cols)
    return b.to_dict()


def page(
    name: str,
    title: str,
    fields: list[FieldRefLike],
    *,
    cols: int | None = None,
) -> ArchPage:
    b = Page.make(name, title).fields(fields)
    if cols is not None:
        b.cols(cols)
    return b.to_dict()


def notebook(
    name: str,
    pages: list[ArchPage],
    *,
    title: str | None = None,
) -> ArchNotebook:
    result: ArchNotebook = {"name": name, "pages": pages}
    if title is not None:
        result["title"] = title
    return result


def card(
    title: str,
    *,
    subtitle: str | None = None,
    fields: list[FieldRefLike] | None = None,
    badges: list[FieldRefLike] | None = None,
    image: str | None = None,
) -> ArchKanbanCard:
    b = KanbanCard.make(title)
    if subtitle is not None:
        b.subtitle(subtitle)
    if fields is not None:
        b.fields(fields)
    if badges is not None:
        b.badges(badges)
    if image is not None:
        b.image(image)
    return b.to_dict()


def list_view(
    name: str,
    model: str,
    fields: list[FieldRefLike],
    *,
    title: str | None = None,
    form_view: str | None = None,
    record_href: str | None = None,
    create_href: str | None = None,
    page_actions: list[dict] | None = None,
    sequence: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> ListView:
    b = ListViewBuilder.make(name).model(model).fields(fields).priority(priority)
    if title is not None:
        b.title(title)
    if form_view is not None:
        b.form_view(form_view)
    if record_href is not None:
        b.record_href(record_href)
    if create_href is not None:
        b.create_href(create_href)
    if page_actions:
        b.page_actions(page_actions)
    if sequence is not None:
        b.sequence(sequence)
    if domain is not None:
        b.domain(domain)
    return b.to_dict()


def form_view(
    name: str,
    model: str,
    sections: list[FormLayoutItem],
    *,
    title: str | None = None,
    header_actions: list[dict] | None = None,
    cols: int | None = None,
    priority: int = 16,
) -> FormView:
    b = FormViewBuilder.make(name).model(model).sections(sections).priority(priority)
    if title is not None:
        b.title(title)
    if header_actions:
        b.header_actions(header_actions)
    if cols is not None:
        b.cols(cols)
    return b.to_dict()


def kanban_view(
    name: str,
    model: str,
    *,
    card: ArchKanbanCard | None = None,
    group_by: str | None = None,
    sequence: str | None = None,
    form_view: str | None = None,
    title: str | None = None,
    priority: int = 16,
) -> KanbanView:
    b = KanbanViewBuilder.make(name).model(model).priority(priority)
    if title is not None:
        b.title(title)
    if card is not None:
        b.card(card)
    if group_by is not None:
        b.group_by(group_by)
    if sequence is not None:
        b.sequence(sequence)
    if form_view is not None:
        b.form_view(form_view)
    return b.to_dict()


def graph_view(
    name: str,
    model: str,
    *,
    groupby: str,
    measure: str,
    chart: str = "bar",
    title: str | None = None,
    stacked: bool | None = None,
    horizontal: bool | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> GraphView:
    b = (
        GraphViewBuilder.make(name)
        .model(model)
        .groupby(groupby)
        .measure(measure)
        .chart(chart)
        .priority(priority)
    )
    if title is not None:
        b.title(title)
    if stacked is not None:
        b.stacked(stacked)
    if horizontal is not None:
        b.horizontal(horizontal)
    if domain is not None:
        b.domain(domain)
    return b.to_dict()


def pivot_view(
    name: str,
    model: str,
    *,
    row_groupby: list[str],
    col_groupby: list[str] | None = None,
    measures: list[str],
    title: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> PivotView:
    b = (
        PivotViewBuilder.make(name)
        .model(model)
        .row_groupby(row_groupby)
        .col_groupby(col_groupby)
        .measures(measures)
        .priority(priority)
    )
    if title is not None:
        b.title(title)
    if domain is not None:
        b.domain(domain)
    return b.to_dict()


def chart_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: str | None = None,
    groupby: str | None = None,
    measure: str = "__count",
    chart: str = "bar",
    domain: list | None = None,
    view: ViewRef | None = None,
    colspan: DashboardColspan = 2,
    perm: str = "read",
) -> DashboardWidget:
    b = ChartWidgetBuilder.make(widget_id).measure(measure).chart(chart).colspan(colspan).perm(perm)
    if title is not None:
        b.title(title)
    if view is not None:
        b.view(view)
    else:
        if model:
            b.model(model)
        if groupby:
            b.groupby(groupby)
        if domain is not None:
            b.domain(domain)
    return b.to_dict()


def table_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: str | None = None,
    fields: list[FieldRefLike] | None = None,
    view: ViewRef | None = None,
    columns: list[str] | None = None,
    domain: list | None = None,
    limit: int = 10,
    order: str | None = None,
    more_href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget:
    b = TableWidgetBuilder.make(widget_id).limit(limit).colspan(colspan).perm(perm)
    if title is not None:
        b.title(title)
    if view is not None:
        b.view(view)
    else:
        if model:
            b.model(model)
        if fields:
            b.fields(fields)
    if columns is not None:
        b.columns(columns)
    if domain is not None:
        b.domain(domain)
    if order is not None:
        b.order(order)
    if more_href is not None:
        b.more_href(more_href)
    return b.to_dict()


def stat_widget(
    widget_id: str,
    *,
    title: str,
    model: str,
    measure: str = "__count",
    domain: list | None = None,
    href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget:
    b = (
        StatWidgetBuilder.make(widget_id)
        .title(title)
        .model(model)
        .measure(measure)
        .colspan(colspan)
        .perm(perm)
    )
    if domain is not None:
        b.domain(domain)
    if href is not None:
        b.href(href)
    return b.to_dict()


def link_widget(
    widget_id: str,
    *,
    title: str,
    subtitle: str,
    description: str,
    url: str,
    colspan: DashboardColspan = 1,
    perm: str = "write",
) -> DashboardWidget:
    return (
        LinkWidgetBuilder.make(widget_id)
        .title(title)
        .subtitle(subtitle)
        .description(description)
        .url(url)
        .colspan(colspan)
        .perm(perm)
        .to_dict()
    )


def dashboard_view(
    name: str,
    *,
    widgets: list[DashboardWidget],
    title: str | None = None,
    subtitle: str | None = None,
    columns: int = 2,
    priority: int = 16,
) -> dict:
    b = DashboardViewBuilder.make(name).widgets(widgets).columns(columns).priority(priority)
    if title is not None:
        b.title(title)
    if subtitle is not None:
        b.subtitle(subtitle)
    return b.to_dict()


def inherit_view(
    name: str,
    inherit: str,
    ops: list[Operation],
    *,
    priority: int = 20,
) -> ViewInherit:
    return (
        InheritViewBuilder.make(name)
        .extends(inherit)
        .operations(ops)
        .priority(priority)
        .to_dict()
    )


def op_remove(target: list[TargetSegment]) -> Operation:
    return {"op": "remove", "target": target}


def op_set(target: list[TargetSegment], value: Any) -> Operation:
    return {"op": "set", "target": target, "value": value}


def op_replace(target: list[TargetSegment], value: Any) -> Operation:
    return {"op": "replace", "target": target, "value": value}


def op_update(target: list[TargetSegment], **attrs: Any) -> Operation:
    return {"op": "update", "target": target, "value": dict(attrs)}


def op_after(target: list[TargetSegment], value: Any) -> Operation:
    return {"op": "after", "target": target, "value": value}


def op_before(target: list[TargetSegment], value: Any) -> Operation:
    return {"op": "before", "target": target, "value": value}
