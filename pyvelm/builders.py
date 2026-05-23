"""Factory helpers for building pyvelm view and menu declarations.

These are pure ergonomic wrappers — every function returns a plain dict
typed as the matching TypedDict so the loader needs no changes. Module
authors who prefer raw dicts can continue using them; builders are
opt-in.

Quick-start
-----------
**Views**::

    from pyvelm.builders import list_view, form_view, kanban_view
    from pyvelm.builders import field, section, card

    VIEWS = [
        list_view("partner.list", "res.partner",
                  fields=["name", "code", field("active", widget="toggle")],
                  form_view="partner.form"),

        form_view("partner.form", "res.partner", sections=[
            section("identity", "Identity", ["name", "code"]),
            section("profile",  "Profile",  ["age", "country_id",
                                              field("active", widget="toggle")]),
        ]),

        kanban_view("partner.kanban", "res.partner",
                    card=card("name", subtitle="code",
                              fields=["age", "country_id"],
                              badges=[field("active", widget="toggle"), "tag_ids"]),
                    group_by="country_id",
                    form_view="partner.form",
                    title="Partner Board"),
    ]

**View inheritance**::

    from pyvelm.builders import inherit_view
    from pyvelm.builders import op_remove, op_after, op_before
    from pyvelm.builders import op_set, op_replace, op_update

    VIEW_INHERITS = [
        inherit_view("partner.list.pro", "partners.partner.list", priority=20, ops=[
            op_remove(["fields", "age"]),
            op_after(["fields", "country_id"], {"name": "tag_ids"}),
            # op_update accepts keyword args — they become the merged dict:
            op_update(["fields", "active"], widget="toggle", readonly=True),
            op_set(["fields", "code", "label"], "Partner code"),
        ]),
    ]

**Menus**::

    from pyvelm.builders import Menus

    m = Menus("partners")  # same string as NAME in __pyvelm__.py

    MENUS = [
        m.group("business", "Business", icon=_ICON_GRID, sequence=50),
        m.item("business.partners", "Partners",
               parent="business", view="partner.list", sequence=10),
        # Cross-module parent (admin owns the group):
        m.item("business.tags", "Tags",
               parent=("admin", "settings"), view="tag.list", sequence=40),
    ]
"""
from __future__ import annotations

from typing import Any

from pyvelm.types import (
    ArchForm,
    ArchGraph,
    ArchKanban,
    ArchKanbanCard,
    ArchList,
    ArchPivot,
    ArchSection,
    FieldRef,
    FieldRefLike,
    FormView,
    GraphView,
    KanbanView,
    ListView,
    Menu,
    Operation,
    PivotView,
    TargetSegment,
    ViewInherit,
    WidgetHint,
)

__all__ = [
    # field / section / card helpers
    "field",
    "section",
    "card",
    # view constructors
    "list_view",
    "form_view",
    "kanban_view",
    "graph_view",
    "pivot_view",
    # view-inherit constructor + op helpers
    "inherit_view",
    "op_after",
    "op_before",
    "op_remove",
    "op_replace",
    "op_set",
    "op_update",
    # menu helpers
    "Menus",
    "menu_group",
    "menu_item",
    "menu_ref",
    "view_href",
]


# ---------------------------------------------------------------------------
# Field / section / card helpers
# ---------------------------------------------------------------------------

def field(
    name: str,
    *,
    widget: WidgetHint | None = None,
    label: str | None = None,
    readonly: bool | None = None,
    required: bool | None = None,
    **extra: Any,
) -> FieldRef:
    """Build a field-spec dict.

    ``name`` is the only required argument. All other kwargs map
    directly to ``FieldRef`` keys and are only included when provided,
    so the resulting dict stays minimal.

    Extra keyword arguments are forwarded as-is (e.g. custom
    ``filter_kind``/``group_kind`` attributes).

    Example::

        field("active", widget="toggle")
        # → {"name": "active", "widget": "toggle"}

        field("code", label="Partner code", readonly=True)
        # → {"name": "code", "label": "Partner code", "readonly": True}
    """
    result: FieldRef = {"name": name}
    if widget is not None:
        result["widget"] = widget
    if label is not None:
        result["label"] = label
    if readonly is not None:
        result["readonly"] = readonly
    if required is not None:
        result["required"] = required
    result.update(extra)  # type: ignore[arg-type]
    return result


def section(
    name: str,
    title: str,
    fields: list[FieldRefLike],
) -> ArchSection:
    """Build a form-view section dict.

    Example::

        section("identity", "Identity", ["name", "code"])
        section("profile",  "Profile",  ["age", field("active", widget="toggle")])
    """
    return {"name": name, "title": title, "fields": fields}


def card(
    title: str,
    *,
    subtitle: str | None = None,
    fields: list[FieldRefLike] | None = None,
    badges: list[FieldRefLike] | None = None,
) -> ArchKanbanCard:
    """Build the ``card`` dict for a kanban arch.

    ``title`` is a field name whose value is rendered as the card
    heading. All other args are optional.

    Example::

        card("name", subtitle="code",
             fields=["age", "country_id"],
             badges=[field("active", widget="toggle"), "tag_ids"])
    """
    result: ArchKanbanCard = {"title": title}
    if subtitle is not None:
        result["subtitle"] = subtitle
    if fields is not None:
        result["fields"] = fields
    if badges is not None:
        result["badges"] = badges
    return result


# ---------------------------------------------------------------------------
# View constructors
# ---------------------------------------------------------------------------

def list_view(
    name: str,
    model: str,
    fields: list[FieldRefLike],
    *,
    title: str | None = None,
    form_view: str | None = None,
    record_href: str | None = None,
    create_href: str | None = None,
    sequence: str | None = None,
    priority: int = 16,
) -> ListView:
    """Declare a ``view_type="list"`` view.

    Args:
        name:       Unique view name (e.g. ``"partner.list"``).
        model:      Dotted model name (e.g. ``"res.partner"``).
        fields:     Ordered list of field names or ``field(...)`` dicts.
        title:      Optional heading shown above the table.
        form_view:  Name of a form view to link each row to.
        record_href: Optional URL for row navigation; ``{id}`` is replaced.
        create_href: Optional URL for the New button (bypasses form create).
        sequence:   Field name of an integer field enabling drag-reorder.
        priority:   Inheritance chain priority (default 16).

    Example::

        list_view("partner.list", "res.partner",
                  fields=["name", "code", field("active", widget="toggle")],
                  form_view="partner.form")
    """
    arch: ArchList = {"fields": fields}
    if title is not None:
        arch["title"] = title
    if form_view is not None:
        arch["form_view"] = form_view
    if record_href is not None:
        arch["record_href"] = record_href
    if create_href is not None:
        arch["create_href"] = create_href
    if sequence is not None:
        arch["sequence"] = sequence
    result: ListView = {
        "name": name,
        "model": model,
        "view_type": "list",
        "arch": arch,
        "priority": priority,
    }
    return result


def form_view(
    name: str,
    model: str,
    sections: list[ArchSection],
    *,
    title: str | None = None,
    header_actions: list[dict] | None = None,
    priority: int = 16,
) -> FormView:
    """Declare a ``view_type="form"`` view.

    Args:
        name:      Unique view name (e.g. ``"partner.form"``).
        model:     Dotted model name (e.g. ``"res.partner"``).
        sections:  List of ``section(...)`` dicts.
        title:     Optional heading override (default: humanized model name).
        header_actions: Optional list of buttons rendered in display
                   mode next to Edit / Delete. Each is a dict with
                   ``label`` and ``url`` (required), plus optional
                   ``method`` (default ``"POST"``) and ``confirm``.
                   ``{id}`` in ``url`` is substituted at render time.
        priority:  Inheritance chain priority (default 16).

    Example::

        form_view("partner.form", "res.partner", sections=[
            section("identity", "Identity", ["name", "code"]),
            section("profile",  "Profile",  ["age", "country_id"]),
        ])
    """
    arch: ArchForm = {"sections": sections}
    if title is not None:
        arch["title"] = title
    if header_actions:
        arch["header_actions"] = list(header_actions)
    result: FormView = {
        "name": name,
        "model": model,
        "view_type": "form",
        "arch": arch,
        "priority": priority,
    }
    return result


def kanban_view(
    name: str,
    model: str,
    *,
    card: ArchKanbanCard | None = None,
    group_by: str | None = None,
    form_view: str | None = None,
    title: str | None = None,
    priority: int = 16,
) -> KanbanView:
    """Declare a ``view_type="kanban"`` view.

    Args:
        name:       Unique view name (e.g. ``"partner.kanban"``).
        model:      Dotted model name (e.g. ``"res.partner"``).
        card:       A ``card(...)`` dict describing the card layout.
        group_by:   Field name to group cards into columns.
        form_view:  Name of a form view each card links to.
        title:      Board heading (e.g. ``"Partner Board"``).
        priority:   Inheritance chain priority (default 16).

    Example::

        kanban_view("partner.kanban", "res.partner",
                    card=card("name", subtitle="code"),
                    group_by="country_id",
                    form_view="partner.form",
                    title="Partner Board")
    """
    arch: ArchKanban = {}
    if title is not None:
        arch["title"] = title
    if card is not None:
        arch["card"] = card
    if group_by is not None:
        arch["group_by"] = group_by
    if form_view is not None:
        arch["form_view"] = form_view
    result: KanbanView = {
        "name": name,
        "model": model,
        "view_type": "kanban",
        "arch": arch,
        "priority": priority,
    }
    return result


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
    """Declare a ``view_type="graph"`` view.

    Args:
        name:        Unique view name (e.g. ``"lead.graph"``).
        model:       Dotted model name (e.g. ``"crm.lead"``).
        groupby:     Field name (optionally ``"<field>:<trunc>"`` on
                     Date/Datetime). Many2one fields are supported and
                     get human labels resolved automatically.
        measure:     ``"<field>"`` or ``"<field>:<agg>"`` where agg ∈
                     ``sum | avg | min | max | count``. ``"__count"``
                     plots the per-group record count.
        chart:       ``"bar" | "line" | "pie"``. Defaults to ``"bar"``.
        title:       Page heading; defaults to the auto-derived model
                     name.
        stacked:     Bar charts only — stack measures (no-op until
                     multi-measure bar lands).
        horizontal:  Bar charts only — render horizontally.
        domain:      Extra static domain ANDed with the URL filters
                     before aggregation.
        priority:    Inheritance chain priority (default 16).

    Example::

        graph_view("lead.graph", "crm.lead",
                   groupby="stage",
                   measure="expected_revenue:sum",
                   chart="bar",
                   title="Pipeline by stage")
    """
    arch: ArchGraph = {"groupby": groupby, "measure": measure}
    if chart:
        arch["chart"] = chart  # type: ignore[typeddict-item]
    if title is not None:
        arch["title"] = title
    if stacked is not None:
        arch["stacked"] = stacked
    if horizontal is not None:
        arch["horizontal"] = horizontal
    if domain is not None:
        arch["domain"] = domain
    return {
        "name": name,
        "model": model,
        "view_type": "graph",
        "arch": arch,
        "priority": priority,
    }


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
    """Declare a ``view_type="pivot"`` view.

    Args:
        name:         Unique view name.
        model:        Dotted model name.
        row_groupby:  Ordered list of field names used to nest rows
                      (outermost first). Same suffix syntax as
                      ``graph_view``'s ``groupby``.
        col_groupby:  Ordered list of field names used to nest columns.
                      Empty / ``None`` means a flat "measures only"
                      column header — each entry in ``measures`` shows
                      as its own column.
        measures:     Measure specs (``"field"`` / ``"field:agg"`` /
                      ``"__count"``). Multiple measures stack as
                      sibling columns under each leaf col group.
        title:        Page heading.
        domain:       Extra static domain ANDed with URL filters.
        priority:     Inheritance chain priority (default 16).

    Example::

        pivot_view("lead.pivot", "crm.lead",
                   row_groupby=["stage"],
                   col_groupby=["priority"],
                   measures=["__count", "expected_revenue:sum"])
    """
    arch: ArchPivot = {
        "row_groupby": list(row_groupby),
        "col_groupby": list(col_groupby or []),
        "measures": list(measures),
    }
    if title is not None:
        arch["title"] = title
    if domain is not None:
        arch["domain"] = domain
    return {
        "name": name,
        "model": model,
        "view_type": "pivot",
        "arch": arch,
        "priority": priority,
    }


# ---------------------------------------------------------------------------
# View-inherit constructor
# ---------------------------------------------------------------------------

def inherit_view(
    name: str,
    inherit: str,
    ops: list[Operation],
    *,
    priority: int = 20,
) -> ViewInherit:
    """Declare a view-inherit extension.

    Args:
        name:     Unique name for this extension view.
        inherit:  ``"<module>.<view_name>"`` of the view to patch.
        ops:      Ordered list of ``op_*()`` operations.
        priority: Resolution priority; higher overrides lower (default 20).

    Example::

        inherit_view("partner.list.pro", "partners.partner.list", priority=20, ops=[
            op_remove(["fields", "age"]),
            op_after(["fields", "country_id"], {"name": "tag_ids"}),
            op_update(["fields", "active"], widget="toggle", readonly=True),
        ])
    """
    return {
        "name": name,
        "inherit": inherit,
        "priority": priority,
        "operations": ops,
    }


# ---------------------------------------------------------------------------
# Operation helpers
# ---------------------------------------------------------------------------

def op_remove(target: list[TargetSegment]) -> Operation:
    """Remove the node at ``target`` from the arch.

    Example::

        op_remove(["fields", "age"])
        op_remove(["sections", "profile", "fields", "parent_id"])
    """
    return {"op": "remove", "target": target}


def op_set(target: list[TargetSegment], value: Any) -> Operation:
    """Set a single attribute at ``target`` to ``value``.

    Use this when you want to write one scalar (string, bool, int) into
    an existing node. For merging multiple attributes at once use
    ``op_update``.

    Example::

        op_set(["fields", "code", "label"], "Partner code")
        op_set(["sections", "profile", "title"], "Demographics")
    """
    return {"op": "set", "target": target, "value": value}


def op_replace(target: list[TargetSegment], value: Any) -> Operation:
    """Replace the node at ``target`` entirely with ``value``.

    Example::

        op_replace(["sections", "profile"], {
            "name": "profile", "title": "Demographics", "fields": ["age"]
        })
    """
    return {"op": "replace", "target": target, "value": value}


def op_update(target: list[TargetSegment], **attrs: Any) -> Operation:
    """Merge keyword arguments into the dict at ``target``.

    This is the ergonomic equivalent of Odoo's
    ``position="attributes"`` — pass each attribute as a keyword arg
    and they are merged into the target node in one operation.

    Example::

        op_update(["fields", "active"], widget="toggle", readonly=True)
        # equivalent raw form:
        # {"op": "update", "target": [...], "value": {"widget": "toggle", "readonly": True}}
    """
    return {"op": "update", "target": target, "value": dict(attrs)}


def op_after(target: list[TargetSegment], value: Any) -> Operation:
    """Insert ``value`` immediately after the node at ``target``.

    ``value`` should match the type of siblings at that level
    (a field-spec dict when inside a ``fields`` list, a section dict
    when inside a ``sections`` list, etc.).

    Example::

        op_after(["fields", "country_id"], {"name": "tag_ids"})
        op_after(["sections", "relations"], {
            "name": "vip", "title": "VIP Status", "fields": ["vip_note"]
        })
    """
    return {"op": "after", "target": target, "value": value}


def op_before(target: list[TargetSegment], value: Any) -> Operation:
    """Insert ``value`` immediately before the node at ``target``.

    Example::

        op_before(["fields", "active"], {"name": "vip_note"})
    """
    return {"op": "before", "target": target, "value": value}


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------

def view_href(module: str, view: str) -> str:
    """URL for a registered list/form/kanban/graph/pivot view.

    ``module`` is the installing module's ``NAME`` (from ``__pyvelm__.py``),
    ``view`` is the view's ``name`` (e.g. ``"partner.list"``).
    """
    return f"/web/views/{module}/{view}"


def menu_ref(module: str, name: str) -> str:
    """Fully qualified menu key ``"<module>.<name>"`` for ``parent=``."""
    return f"{module}.{name}"


def _resolve_menu_parent(
    parent: str | tuple[str, str],
    *,
    menu_module: str,
) -> str:
    if isinstance(parent, tuple):
        return menu_ref(parent[0], parent[1])
    if "." in parent:
        return parent
    return menu_ref(menu_module, parent)


def _resolve_menu_href(
    *,
    href: str | None,
    view: str | None,
    view_module: str | None,
    menu_module: str | None,
) -> str:
    if href is not None and view is not None:
        raise ValueError("menu item: pass href= or view=, not both")
    if href is not None:
        return href
    if view is None:
        raise ValueError("menu item: href= or view= is required")
    mod = view_module or menu_module
    if not mod:
        raise ValueError(
            "menu item: view= requires view_module= or menu_module= "
            "(or use Menus(module).item(...))"
        )
    return view_href(mod, view)


class Menus:
    """Fluent builder for a module's ``MENUS`` list.

    Resolves **parent** from a short group name (``"business"`` →
    ``"<this-module>.business"``) or a ``(module, name)`` tuple for
    cross-module groups. Resolves **view** to ``/web/views/<module>/<view>``.

    Args:
        module: Installing module name — the ``NAME`` in ``__pyvelm__.py``.
    """

    def __init__(self, module: str) -> None:
        self.module = module

    def ref(self, name: str) -> str:
        """This module's menu key (for documentation / debugging)."""
        return menu_ref(self.module, name)

    def parent(
        self,
        name: str,
        *,
        module: str | None = None,
    ) -> str:
        """Parent reference for ``parent=`` on :func:`item`."""
        return menu_ref(module or self.module, name)

    def view(self, name: str, *, module: str | None = None) -> str:
        """View URL in this module (or another with ``module=``)."""
        return view_href(module or self.module, name)

    def group(
        self,
        name: str,
        label: str,
        *,
        icon: str | None = None,
        sequence: int = 10,
    ) -> Menu:
        return menu_group(name, label, icon=icon, sequence=sequence)

    def item(
        self,
        name: str,
        label: str,
        *,
        href: str | None = None,
        view: str | None = None,
        view_module: str | None = None,
        parent: str | tuple[str, str] | None = None,
        icon: str | None = None,
        sequence: int = 10,
    ) -> Menu:
        """Leaf sidebar entry.

        Pass ``view="partner.list"`` (same ``name`` as in ``VIEWS``) instead
        of a full ``href``. Pass ``parent="business"`` for a group in this
        module, or ``parent=("admin", "settings")`` for another module's group.
        Use ``href=`` for non-view routes (e.g. ``"/web/apps"``).
        """
        resolved_href = _resolve_menu_href(
            href=href,
            view=view,
            view_module=view_module,
            menu_module=self.module,
        )
        resolved_parent = (
            _resolve_menu_parent(parent, menu_module=self.module)
            if parent is not None
            else None
        )
        return menu_item(
            name,
            label,
            href=resolved_href,
            parent=resolved_parent,
            icon=icon,
            sequence=sequence,
        )


def menu_group(
    name: str,
    label: str,
    *,
    icon: str | None = None,
    sequence: int = 10,
) -> Menu:
    """Declare a top-level sidebar group (no ``href``, no ``parent``).

    Args:
        name:     Unique name within the module (e.g. ``"business"``).
        label:    Display text in the sidebar.
        icon:     SVG string rendered next to the label.
        sequence: Ordering among siblings (lower = higher up).

    Example::

        menu_group("business", "Business", icon=_ICON_GRID, sequence=50)
    """
    result: Menu = {"name": name, "label": label, "sequence": sequence}
    if icon is not None:
        result["icon"] = icon
    return result


def menu_item(
    name: str,
    label: str,
    *,
    href: str | None = None,
    view: str | None = None,
    menu_module: str | None = None,
    view_module: str | None = None,
    parent: str | tuple[str, str] | None = None,
    icon: str | None = None,
    sequence: int = 10,
) -> Menu:
    """Declare a leaf sidebar entry.

    Prefer :class:`Menus` for ergonomic ``parent`` / ``view`` resolution.
    Low-level callers may pass full ``href`` and ``parent="module.group"``,
    or use ``view=`` + ``menu_module=`` with a short ``parent=`` name.

    Args:
        name:         Unique name within the module (e.g. ``"business.partners"``).
        label:        Display text in the sidebar.
        href:         URL (required unless ``view=`` is set).
        view:         View ``name``; builds ``/web/views/<module>/<view>``.
        menu_module:  Installing module — required for short ``parent=`` names.
        view_module:  Module that owns the view (defaults to ``menu_module``).
        parent:       Group key — full ``"module.name"``, short ``"business"``
                      (needs ``menu_module=``), or ``("admin", "settings")``.
        icon:         SVG for root-level standalone items (Dashboard, Apps).
        sequence:     Ordering among siblings (lower = higher up).
    """
    resolved_href = _resolve_menu_href(
        href=href,
        view=view,
        view_module=view_module,
        menu_module=menu_module,
    )
    result: Menu = {"name": name, "label": label, "href": resolved_href, "sequence": sequence}
    if parent is not None:
        if (
            menu_module is None
            and isinstance(parent, str)
            and "." not in parent
        ):
            raise ValueError(
                f"Menu parent {parent!r} is a short name; pass menu_module= "
                "or use Menus(module).item(...)"
            )
        if isinstance(parent, tuple):
            result["parent"] = menu_ref(parent[0], parent[1])
        elif isinstance(parent, str) and "." in parent:
            result["parent"] = parent
        else:
            result["parent"] = menu_ref(menu_module, parent)  # type: ignore[arg-type]
    if icon is not None:
        result["icon"] = icon
    return result
