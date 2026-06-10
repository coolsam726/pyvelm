"""Fluent view declaration builders."""
from __future__ import annotations

from typing import Any

from pyvelm.types import (
    ArchDashboard,
    ArchDetail,
    ArchForm,
    ArchGraph,
    ArchKanban,
    ArchKanbanCard,
    ArchList,
    ArchPivot,
    DashboardColspan,
    DashboardView,
    DashboardWidget,
    FieldRefLike,
    FormLayoutItem,
    DetailView,
    FormView,
    GraphView,
    KanbanView,
    ListView,
    Operation,
    PivotView,
    ViewInherit,
    ViewRef,
)

from ._normalize import field_specs
from .layout import KanbanCard, Notebook, Page, Section


class ListViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._fields: list[FieldRefLike | Any] = []
        self._title: str | None = None
        self._form_view: str | None = None
        self._record_href: str | None = None
        self._create_href: str | None = None
        self._page_actions: list[dict] | None = None
        self._sequence: str | None = None
        self._domain: list | None = None
        self._detail_view: str | None = None
        self._bulk_actions: list[dict] | None = None
        self._row_actions: list[dict] | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> ListViewBuilder:
        return cls(name)

    def model(self, model: str) -> ListViewBuilder:
        self._model = model
        return self

    def fields(self, fields: list[FieldRefLike | Any]) -> ListViewBuilder:
        self._fields = list(fields)
        return self

    def columns(self, fields: list[FieldRefLike | Any]) -> ListViewBuilder:
        return self.fields(fields)

    def title(self, title: str) -> ListViewBuilder:
        self._title = title
        return self

    def form_view(self, form_view: str) -> ListViewBuilder:
        self._form_view = form_view
        return self

    def record_href(self, record_href: str) -> ListViewBuilder:
        self._record_href = record_href
        return self

    def create_href(self, create_href: str) -> ListViewBuilder:
        self._create_href = create_href
        return self

    def page_actions(self, page_actions: list[dict]) -> ListViewBuilder:
        self._page_actions = list(page_actions)
        return self

    def sequence(self, sequence: str) -> ListViewBuilder:
        self._sequence = sequence
        return self

    def domain(self, domain: list) -> ListViewBuilder:
        self._domain = list(domain)
        return self

    def detail_view(self, detail_view: str) -> ListViewBuilder:
        self._detail_view = detail_view
        return self

    def bulk_actions(self, bulk_actions: list[dict]) -> ListViewBuilder:
        self._bulk_actions = list(bulk_actions)
        return self

    def row_actions(self, row_actions: list[dict]) -> ListViewBuilder:
        self._row_actions = list(row_actions)
        return self

    def priority(self, priority: int) -> ListViewBuilder:
        self._priority = priority
        return self

    def to_dict(self) -> ListView:
        if not self._model:
            raise ValueError(f"List view {self._name!r} is missing model().")
        arch: ArchList = {"fields": field_specs(self._fields)}
        if self._title is not None:
            arch["title"] = self._title
        if self._form_view is not None:
            arch["form_view"] = self._form_view
        if self._record_href is not None:
            arch["record_href"] = self._record_href
        if self._create_href is not None:
            arch["create_href"] = self._create_href
        if self._page_actions:
            arch["page_actions"] = list(self._page_actions)
        if self._sequence is not None:
            arch["sequence"] = self._sequence
        if self._domain is not None:
            arch["domain"] = self._domain
        if self._detail_view is not None:
            arch["detail_view"] = self._detail_view
        if self._bulk_actions:
            arch["bulk_actions"] = list(self._bulk_actions)
        if self._row_actions:
            arch["row_actions"] = list(self._row_actions)
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "list",
            "arch": arch,
            "priority": self._priority,
        }


class FormViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._sections: list[FormLayoutItem] = []
        self._title: str | None = None
        self._header_actions: list[dict] | None = None
        self._cols: int | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> FormViewBuilder:
        return cls(name)

    def model(self, model: str) -> FormViewBuilder:
        self._model = model
        return self

    def title(self, title: str) -> FormViewBuilder:
        self._title = title
        return self

    def cols(self, cols: int) -> FormViewBuilder:
        self._cols = cols
        return self

    def header_actions(self, header_actions: list[dict]) -> FormViewBuilder:
        self._header_actions = list(header_actions)
        return self

    def priority(self, priority: int) -> FormViewBuilder:
        self._priority = priority
        return self

    def section(
        self,
        name: str,
        title: str,
        fields: list[FieldRefLike | Any],
        *,
        cols: int | None = None,
    ) -> FormViewBuilder:
        block = Section.make(name, title).fields(fields)
        if cols is not None:
            block.cols(cols)
        self._sections.append(block.to_dict())
        return self

    def notebook(
        self,
        name: str,
        title: str,
        pages: list[Page | dict],
        *,
        cols: int | None = None,
    ) -> FormViewBuilder:
        nb = Notebook.make(name).title(title).pages(
            [p if isinstance(p, Page) else Page.make(p["name"], p.get("title", p["name"])).fields(p.get("fields", [])) for p in pages]  # type: ignore[arg-type]
        )
        entry = nb.to_dict()
        if cols is not None:
            entry["cols"] = cols
        self._sections.append(entry)
        return self

    def sections(self, sections: list[FormLayoutItem]) -> FormViewBuilder:
        self._sections = list(sections)
        return self

    def to_dict(self) -> FormView:
        if not self._model:
            raise ValueError(f"Form view {self._name!r} is missing model().")
        arch: ArchForm = {"sections": self._sections}
        if self._title is not None:
            arch["title"] = self._title
        if self._header_actions:
            arch["header_actions"] = list(self._header_actions)
        if self._cols is not None:
            arch["cols"] = self._cols
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "form",
            "arch": arch,
            "priority": self._priority,
        }


class DetailViewBuilder:
    """Read-only record view — same layout as a form, no inline edit."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._sections: list[FormLayoutItem] = []
        self._title: str | None = None
        self._header_actions: list[dict] | None = None
        self._form_view: str | None = None
        self._cols: int | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> DetailViewBuilder:
        return cls(name)

    def model(self, model: str) -> DetailViewBuilder:
        self._model = model
        return self

    def title(self, title: str) -> DetailViewBuilder:
        self._title = title
        return self

    def cols(self, cols: int) -> DetailViewBuilder:
        self._cols = cols
        return self

    def form_view(self, form_view: str) -> DetailViewBuilder:
        self._form_view = form_view
        return self

    def header_actions(self, header_actions: list[dict]) -> DetailViewBuilder:
        self._header_actions = list(header_actions)
        return self

    def priority(self, priority: int) -> DetailViewBuilder:
        self._priority = priority
        return self

    def section(
        self,
        name: str,
        title: str,
        fields: list[FieldRefLike | Any],
        *,
        cols: int | None = None,
    ) -> DetailViewBuilder:
        block = Section.make(name, title).fields(fields)
        if cols is not None:
            block.cols(cols)
        self._sections.append(block.to_dict())
        return self

    def notebook(
        self,
        name: str,
        title: str,
        pages: list[Page | dict],
        *,
        cols: int | None = None,
    ) -> DetailViewBuilder:
        nb = Notebook.make(name).title(title).pages(
            [p if isinstance(p, Page) else Page.make(p["name"], p.get("title", p["name"])).fields(p.get("fields", [])) for p in pages]  # type: ignore[arg-type]
        )
        entry = nb.to_dict()
        if cols is not None:
            entry["cols"] = cols
        self._sections.append(entry)
        return self

    def sections(self, sections: list[FormLayoutItem]) -> DetailViewBuilder:
        self._sections = list(sections)
        return self

    def to_dict(self) -> DetailView:
        if not self._model:
            raise ValueError(f"Detail view {self._name!r} is missing model().")
        arch: ArchDetail = {"sections": self._sections}
        if self._title is not None:
            arch["title"] = self._title
        if self._header_actions:
            arch["header_actions"] = list(self._header_actions)
        if self._form_view is not None:
            arch["form_view"] = self._form_view
        if self._cols is not None:
            arch["cols"] = self._cols
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "detail",
            "arch": arch,
            "priority": self._priority,
        }


class KanbanViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._card: ArchKanbanCard | None = None
        self._group_by: str | None = None
        self._sequence: str | None = None
        self._form_view: str | None = None
        self._title: str | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> KanbanViewBuilder:
        return cls(name)

    def model(self, model: str) -> KanbanViewBuilder:
        self._model = model
        return self

    def card(self, card: KanbanCard | ArchKanbanCard) -> KanbanViewBuilder:
        self._card = card.to_dict() if isinstance(card, KanbanCard) else card
        return self

    def group_by(self, group_by: str) -> KanbanViewBuilder:
        self._group_by = group_by
        return self

    def sequence(self, sequence: str) -> KanbanViewBuilder:
        self._sequence = sequence
        return self

    def form_view(self, form_view: str) -> KanbanViewBuilder:
        self._form_view = form_view
        return self

    def title(self, title: str) -> KanbanViewBuilder:
        self._title = title
        return self

    def priority(self, priority: int) -> KanbanViewBuilder:
        self._priority = priority
        return self

    def to_dict(self) -> KanbanView:
        if not self._model:
            raise ValueError(f"Kanban view {self._name!r} is missing model().")
        arch: ArchKanban = {}
        if self._title is not None:
            arch["title"] = self._title
        if self._card is not None:
            arch["card"] = self._card
        if self._group_by is not None:
            arch["group_by"] = self._group_by
        if self._sequence is not None:
            arch["sequence"] = self._sequence
        if self._form_view is not None:
            arch["form_view"] = self._form_view
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "kanban",
            "arch": arch,
            "priority": self._priority,
        }


class GraphViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._groupby: str | None = None
        self._measure: str | None = None
        self._chart = "bar"
        self._title: str | None = None
        self._stacked: bool | None = None
        self._horizontal: bool | None = None
        self._domain: list | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> GraphViewBuilder:
        return cls(name)

    def model(self, model: str) -> GraphViewBuilder:
        self._model = model
        return self

    def groupby(self, groupby: str) -> GraphViewBuilder:
        self._groupby = groupby
        return self

    def measure(self, measure: str) -> GraphViewBuilder:
        self._measure = measure
        return self

    def chart(self, chart: str) -> GraphViewBuilder:
        self._chart = chart
        return self

    def title(self, title: str) -> GraphViewBuilder:
        self._title = title
        return self

    def stacked(self, stacked: bool = True) -> GraphViewBuilder:
        self._stacked = stacked
        return self

    def horizontal(self, horizontal: bool = True) -> GraphViewBuilder:
        self._horizontal = horizontal
        return self

    def domain(self, domain: list) -> GraphViewBuilder:
        self._domain = list(domain)
        return self

    def priority(self, priority: int) -> GraphViewBuilder:
        self._priority = priority
        return self

    def to_dict(self) -> GraphView:
        if not self._model or not self._groupby or not self._measure:
            raise ValueError(f"Graph view {self._name!r} requires model(), groupby(), measure().")
        arch: ArchGraph = {"groupby": self._groupby, "measure": self._measure}
        if self._chart:
            arch["chart"] = self._chart  # type: ignore[typeddict-item]
        if self._title is not None:
            arch["title"] = self._title
        if self._stacked is not None:
            arch["stacked"] = self._stacked
        if self._horizontal is not None:
            arch["horizontal"] = self._horizontal
        if self._domain is not None:
            arch["domain"] = self._domain
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "graph",
            "arch": arch,
            "priority": self._priority,
        }


class PivotViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._model: str | None = None
        self._row_groupby: list[str] = []
        self._col_groupby: list[str] | None = None
        self._measures: list[str] = []
        self._title: str | None = None
        self._domain: list | None = None
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> PivotViewBuilder:
        return cls(name)

    def model(self, model: str) -> PivotViewBuilder:
        self._model = model
        return self

    def row_groupby(self, row_groupby: list[str]) -> PivotViewBuilder:
        self._row_groupby = list(row_groupby)
        return self

    def col_groupby(self, col_groupby: list[str] | None) -> PivotViewBuilder:
        self._col_groupby = list(col_groupby or [])
        return self

    def measures(self, measures: list[str]) -> PivotViewBuilder:
        self._measures = list(measures)
        return self

    def title(self, title: str) -> PivotViewBuilder:
        self._title = title
        return self

    def domain(self, domain: list) -> PivotViewBuilder:
        self._domain = list(domain)
        return self

    def priority(self, priority: int) -> PivotViewBuilder:
        self._priority = priority
        return self

    def to_dict(self) -> PivotView:
        if not self._model:
            raise ValueError(f"Pivot view {self._name!r} is missing model().")
        arch: ArchPivot = {
            "row_groupby": list(self._row_groupby),
            "col_groupby": list(self._col_groupby or []),
            "measures": list(self._measures),
        }
        if self._title is not None:
            arch["title"] = self._title
        if self._domain is not None:
            arch["domain"] = self._domain
        return {
            "name": self._name,
            "model": self._model,
            "view_type": "pivot",
            "arch": arch,
            "priority": self._priority,
        }


class InheritViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._inherit = ""
        self._priority = 20
        self._operations: list[Operation] = []

    @classmethod
    def make(cls, name: str) -> InheritViewBuilder:
        return cls(name)

    def extends(self, inherit: str) -> InheritViewBuilder:
        self._inherit = inherit
        return self

    def inherit(self, inherit: str) -> InheritViewBuilder:
        return self.extends(inherit)

    def priority(self, priority: int) -> InheritViewBuilder:
        self._priority = priority
        return self

    def operations(self, ops: list[Operation]) -> InheritViewBuilder:
        self._operations = list(ops)
        return self

    def operation(self, op: Operation) -> InheritViewBuilder:
        self._operations.append(op)
        return self

    def to_dict(self) -> ViewInherit:
        if not self._inherit:
            raise ValueError(f"Inherit view {self._name!r} is missing extends().")
        return {
            "name": self._name,
            "inherit": self._inherit,
            "priority": self._priority,
            "operations": self._operations,
        }


def _widget(widget_id: str, widget_type: str, **extra: Any) -> DashboardWidget:
    result: DashboardWidget = {"id": widget_id, "type": widget_type}  # type: ignore[typeddict-item]
    result.update(extra)  # type: ignore[typeddict-item]
    return result


class ChartWidgetBuilder:
    def __init__(self, widget_id: str) -> None:
        self._id = widget_id
        self._title: str | None = None
        self._model: str | None = None
        self._groupby: str | None = None
        self._measure = "__count"
        self._chart = "bar"
        self._domain: list | None = None
        self._view: ViewRef | None = None
        self._colspan: DashboardColspan = 2
        self._perm = "read"

    @classmethod
    def make(cls, widget_id: str) -> ChartWidgetBuilder:
        return cls(widget_id)

    def title(self, title: str) -> ChartWidgetBuilder:
        self._title = title
        return self

    def model(self, model: str) -> ChartWidgetBuilder:
        self._model = model
        return self

    def groupby(self, groupby: str) -> ChartWidgetBuilder:
        self._groupby = groupby
        return self

    def measure(self, measure: str) -> ChartWidgetBuilder:
        self._measure = measure
        return self

    def chart(self, chart: str) -> ChartWidgetBuilder:
        self._chart = chart
        return self

    def domain(self, domain: list) -> ChartWidgetBuilder:
        self._domain = list(domain)
        return self

    def view(self, view: ViewRef) -> ChartWidgetBuilder:
        self._view = view
        return self

    def colspan(self, colspan: DashboardColspan) -> ChartWidgetBuilder:
        self._colspan = colspan
        return self

    def perm(self, perm: str) -> ChartWidgetBuilder:
        self._perm = perm
        return self

    def to_dict(self) -> DashboardWidget:
        w = _widget(self._id, "chart", colspan=self._colspan, perm=self._perm)
        if self._title is not None:
            w["title"] = self._title
        if self._view is not None:
            w["view"] = self._view
        else:
            if not self._model or not self._groupby:
                raise ValueError("chart widget: set view() or both model() and groupby()")
            w["model"] = self._model
            w["groupby"] = self._groupby
            w["measure"] = self._measure
            w["chart"] = self._chart  # type: ignore[typeddict-item]
            if self._domain is not None:
                w["domain"] = self._domain
        return w


class TableWidgetBuilder:
    def __init__(self, widget_id: str) -> None:
        self._id = widget_id
        self._title: str | None = None
        self._model: str | None = None
        self._fields: list[FieldRefLike | Any] | None = None
        self._view: ViewRef | None = None
        self._columns: list[str] | None = None
        self._domain: list | None = None
        self._limit = 10
        self._order: str | None = None
        self._more_href: str | None = None
        self._colspan: DashboardColspan = 1
        self._perm = "read"

    @classmethod
    def make(cls, widget_id: str) -> TableWidgetBuilder:
        return cls(widget_id)

    def title(self, title: str) -> TableWidgetBuilder:
        self._title = title
        return self

    def model(self, model: str) -> TableWidgetBuilder:
        self._model = model
        return self

    def fields(self, fields: list[FieldRefLike | Any]) -> TableWidgetBuilder:
        self._fields = list(fields)
        return self

    def view(self, view: ViewRef) -> TableWidgetBuilder:
        self._view = view
        return self

    def columns(self, columns: list[str]) -> TableWidgetBuilder:
        self._columns = list(columns)
        return self

    def domain(self, domain: list) -> TableWidgetBuilder:
        self._domain = list(domain)
        return self

    def limit(self, limit: int) -> TableWidgetBuilder:
        self._limit = limit
        return self

    def order(self, order: str) -> TableWidgetBuilder:
        self._order = order
        return self

    def more_href(self, more_href: str) -> TableWidgetBuilder:
        self._more_href = more_href
        return self

    def colspan(self, colspan: DashboardColspan) -> TableWidgetBuilder:
        self._colspan = colspan
        return self

    def perm(self, perm: str) -> TableWidgetBuilder:
        self._perm = perm
        return self

    def to_dict(self) -> DashboardWidget:
        w = _widget(self._id, "table", limit=self._limit, colspan=self._colspan, perm=self._perm)
        if self._title is not None:
            w["title"] = self._title
        if self._view is not None:
            w["view"] = self._view
        else:
            if not self._model or not self._fields:
                raise ValueError("table widget: set view() or both model() and fields()")
            w["model"] = self._model
            w["fields"] = [
                f.to_dict() if hasattr(f, "to_dict") and not isinstance(f, dict) else f
                for f in self._fields
            ]
        if self._columns is not None:
            w["columns"] = list(self._columns)
        if self._domain is not None:
            w["domain"] = self._domain
        if self._order is not None:
            w["order"] = self._order
        if self._more_href is not None:
            w["more_href"] = self._more_href
        return w


class StatWidgetBuilder:
    def __init__(self, widget_id: str) -> None:
        self._id = widget_id
        self._title = ""
        self._model = ""
        self._measure = "__count"
        self._domain: list | None = None
        self._href: str | None = None
        self._colspan: DashboardColspan = 1
        self._perm = "read"

    @classmethod
    def make(cls, widget_id: str) -> StatWidgetBuilder:
        return cls(widget_id)

    def title(self, title: str) -> StatWidgetBuilder:
        self._title = title
        return self

    def model(self, model: str) -> StatWidgetBuilder:
        self._model = model
        return self

    def measure(self, measure: str) -> StatWidgetBuilder:
        self._measure = measure
        return self

    def domain(self, domain: list) -> StatWidgetBuilder:
        self._domain = list(domain)
        return self

    def href(self, href: str) -> StatWidgetBuilder:
        self._href = href
        return self

    def colspan(self, colspan: DashboardColspan) -> StatWidgetBuilder:
        self._colspan = colspan
        return self

    def perm(self, perm: str) -> StatWidgetBuilder:
        self._perm = perm
        return self

    def to_dict(self) -> DashboardWidget:
        w = _widget(
            self._id,
            "stat",
            title=self._title,
            model=self._model,
            measure=self._measure,
            colspan=self._colspan,
            perm=self._perm,
        )
        if self._domain is not None:
            w["domain"] = self._domain
        if self._href is not None:
            w["href"] = self._href
        return w


class LinkWidgetBuilder:
    def __init__(self, widget_id: str) -> None:
        self._id = widget_id
        self._title = ""
        self._subtitle = ""
        self._description = ""
        self._url = ""
        self._colspan: DashboardColspan = 1
        self._perm = "write"

    @classmethod
    def make(cls, widget_id: str) -> LinkWidgetBuilder:
        return cls(widget_id)

    def title(self, title: str) -> LinkWidgetBuilder:
        self._title = title
        return self

    def subtitle(self, subtitle: str) -> LinkWidgetBuilder:
        self._subtitle = subtitle
        return self

    def description(self, description: str) -> LinkWidgetBuilder:
        self._description = description
        return self

    def url(self, url: str) -> LinkWidgetBuilder:
        self._url = url
        return self

    def colspan(self, colspan: DashboardColspan) -> LinkWidgetBuilder:
        self._colspan = colspan
        return self

    def perm(self, perm: str) -> LinkWidgetBuilder:
        self._perm = perm
        return self

    def to_dict(self) -> DashboardWidget:
        return _widget(
            self._id,
            "link",
            title=self._title,
            subtitle=self._subtitle,
            description=self._description,
            url=self._url,
            colspan=self._colspan,
            perm=self._perm,
        )


class DashboardViewBuilder:
    def __init__(self, name: str) -> None:
        self._name = name
        self._widgets: list[DashboardWidget] = []
        self._title: str | None = None
        self._subtitle: str | None = None
        self._columns = 2
        self._priority = 16

    @classmethod
    def make(cls, name: str) -> DashboardViewBuilder:
        return cls(name)

    def title(self, title: str) -> DashboardViewBuilder:
        self._title = title
        return self

    def subtitle(self, subtitle: str) -> DashboardViewBuilder:
        self._subtitle = subtitle
        return self

    def columns(self, columns: int) -> DashboardViewBuilder:
        self._columns = columns
        return self

    def widgets(self, widgets: list[DashboardWidget | Any]) -> DashboardViewBuilder:
        self._widgets = [
            w.to_dict() if hasattr(w, "to_dict") and not isinstance(w, dict) else w
            for w in widgets
        ]
        return self

    def priority(self, priority: int) -> DashboardViewBuilder:
        self._priority = priority
        return self

    def to_dict(self) -> DashboardView:
        if self._columns < 1 or self._columns > 6:
            raise ValueError("dashboard view: columns must be between 1 and 6")
        arch: ArchDashboard = {"widgets": self._widgets, "columns": self._columns}
        if self._title is not None:
            arch["title"] = self._title
        if self._subtitle is not None:
            arch["subtitle"] = self._subtitle
        return {
            "name": self._name,
            "model": "dashboard",
            "view_type": "dashboard",
            "arch": arch,
            "priority": self._priority,
        }


# Public aliases (Filament / velmphp naming).
ListView = ListViewBuilder
FormView = FormViewBuilder
DetailView = DetailViewBuilder
KanbanView = KanbanViewBuilder
GraphView = GraphViewBuilder
PivotView = PivotViewBuilder
InheritView = InheritViewBuilder
DashboardView = DashboardViewBuilder
ChartWidget = ChartWidgetBuilder
TableWidget = TableWidgetBuilder
StatWidget = StatWidgetBuilder
LinkWidget = LinkWidgetBuilder
