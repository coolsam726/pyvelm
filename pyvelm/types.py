"""Static-typing helpers for manifest and view authoring.

These exist purely so IDE-side tools (Pylance/Pyright, mypy) can flag
typos, missing required keys, and shape mismatches at edit time. They
have no runtime effect — the loader still does duck-typed reads of
each module's globals. Apps that don't use a type checker can ignore
this module entirely.

Recommended usage in a data file:

    from pyvelm.types import ListView, FormView

    VIEWS: list[View] = [
        ListView(
            name="partner.list",
            model="res.partner",
            view_type="list",
            arch={"fields": ["name", "code"]},
        ),
    ]

Or, for maximum ergonomics, use the builder helpers in ``pyvelm.builders``:

    from pyvelm.builders import list_view, form_view, section

    VIEWS = [
        list_view("partner.list", "res.partner", fields=["name", "code"]),
        form_view("partner.form", "res.partner", sections=[
            section("identity", "Identity", ["name", "code"]),
        ]),
    ]

In a manifest, annotate each global individually:

    from pyvelm.types import Manifest

    NAME: str = "partners"
    VERSION: tuple[int, ...] = (0, 2, 0)
    DEPENDS: list[str] = ["base"]
    DATA: list[str] = ["views/partner.py"]

(There is no module-level "Manifest" assignment because the loader
reads individual attributes, not a single dict. The Manifest
TypedDict below exists for the convenience of tools that want to
validate a manifest as a whole — e.g. a future `pyvelm lint`.)
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict, Union


# ---- widget hints --------------------------------------------------
#
# Field-spec dicts may carry a ``widget`` key that picks a named
# renderer variant. ``WidgetHint`` enumerates the values the registry
# actually understands — Pyright will autocomplete from this set and
# flag typos like ``widget="toogle"`` at edit time. Extending the
# registry with a new hint means adding the string here too.

WidgetHint = Literal[
    "toggle",
    # Relational (One2many / Many2many) — edit UX on parent forms:
    # ``dialog`` (default when a comodel form view exists): chips or
    # read-only table; create/edit in the floating dialog.
    # ``inline`` / ``table``: editable inline table (O2m) or chip search (M2m).
    "dialog",
    "inline",
    "table",
]


# ---- field references inside arch ---------------------------------

class _FieldRefRequired(TypedDict):
    name: str


class FieldRef(_FieldRefRequired, total=False):
    """One field entry inside an arch list (list.fields,
    form.sections[*].fields, kanban.card.fields, kanban.card.badges).

    Authoring sugar: a bare string ``"name"`` is equivalent to
    ``{"name": "name"}``. The normalizer rewrites strings to dicts on
    storage so inheritance has stable addresses.

    ``name`` is the only required key. Everything else is optional
    and surface only when the matching renderer / form-control honors
    it (``widget`` → widget registry, ``required`` → red ``*`` + the
    server-side validator, etc.). App-specific attributes that aren't
    in this list are still accepted by the loader at runtime; the
    type checker just won't autocomplete them.
    """

    widget: WidgetHint
    label: str
    readonly: bool
    required: bool
    visible: bool
    # Form-grid only: how many columns of the surrounding section this
    # field's cell spans. ``"full"`` (or an integer >= the section's
    # ``cols``) makes the cell occupy the full row. Ignored on list /
    # kanban / graph / pivot.
    colspan: Union[int, Literal["full"]]


# Authoring form: string or dict.
FieldRefLike = Union[str, FieldRef]


# ---- per-view-type arch shapes ----

class _ArchListRequired(TypedDict):
    fields: list[FieldRefLike]


class ArchList(_ArchListRequired, total=False):
    """Arch for ``view_type="list"`` views.

    Only ``fields`` is required. Optional keys:

    - ``title``     — human-readable heading shown above the table.
    - ``form_view`` — ``"<name>"`` of a form view to link each row to.
    - ``record_href`` — URL pattern for row clicks; ``{id}`` is substituted.
    - ``create_href`` — URL for the list's New button (full navigation).
    - ``sequence``  — name of an integer field; when set the renderer
                      adds a drag handle and forces sort by that field.
    """

    title: str
    form_view: str
    record_href: str
    create_href: str
    sequence: str


class _ArchSectionRequired(TypedDict):
    name: str
    title: str
    fields: list[FieldRefLike]


class ArchSection(_ArchSectionRequired, total=False):
    """One section of a form view.

    ``name``, ``title`` and ``fields`` are required. ``cols`` overrides
    the form-level column count for the fields rendered inside this
    section (default: the form's ``cols``, which defaults to 2).
    """

    cols: int


class ArchHeaderAction(TypedDict, total=False):
    """One button rendered in the form's display-mode action toolbar.

    Keys:

    - ``label``   — button text (required).
    - ``url``     — endpoint to hit; ``{id}`` is substituted with the
                    current record id at render time.
    - ``method``  — HTTP verb, default ``"POST"``.
    - ``confirm`` — optional confirmation prompt; when set, the button
                    asks before firing.
    - ``perm``    — CRUD permission (``read`` / ``write`` / ``create`` /
                    ``unlink``) required to *see* this action. When the
                    current user lacks it, the button is hidden instead
                    of rendered-then-denied. Omit for actions any reader
                    may run.
    - ``model``   — model the ``perm`` check targets; defaults to the
                    view's own model.
    """

    label: str
    url: str
    method: str
    confirm: str
    perm: str
    model: str
    policy: str


class _ArchFormRequired(TypedDict):
    sections: list[ArchSection]


class ArchForm(_ArchFormRequired, total=False):
    """Arch for ``view_type="form"`` views.

    Only ``sections`` is required. Optional keys:

    - ``title`` — overrides the auto-generated page heading.
    - ``header_actions`` — list of buttons rendered next to Edit /
      Delete in display mode (e.g. "Run Now" on a cron form).
    - ``cols`` — number of columns each section uses (default 2). Each
      ``field(...)`` may set ``colspan`` to span multiple cells; a
      section may override ``cols`` for its own block.
    """

    title: str
    header_actions: list[ArchHeaderAction]
    cols: int


class ArchKanbanCard(TypedDict, total=False):
    title: str
    subtitle: str
    fields: list[FieldRefLike]
    badges: list[FieldRefLike]
    image: str


class ArchKanban(TypedDict, total=False):
    """Arch for ``view_type="kanban"`` views. All keys are optional."""

    title: str
    card: ArchKanbanCard
    group_by: str
    sequence: str
    form_view: str


class _ArchGraphRequired(TypedDict):
    # Field name (with optional ``:day|week|month|quarter|year`` suffix
    # on a Date/Datetime field) used to bucket records along the chart's
    # x-axis. Many2one is allowed — the renderer resolves labels via
    # ``read_group``'s built-in M2o label resolution.
    groupby: str
    # Measure spec — ``"field"`` or ``"field:agg"`` where agg ∈ ``sum |
    # avg | min | max | count``. Use ``"__count"`` for the row count.
    measure: str


class ArchGraph(_ArchGraphRequired, total=False):
    """Arch for ``view_type="graph"`` views.

    Required keys are ``groupby`` and ``measure``. Optional:

    - ``title``     — page heading (defaults to the model's plural form).
    - ``chart``     — ``"bar" | "line" | "pie"`` (default ``"bar"``).
    - ``stacked``   — bar charts only: stack measures (no-op until we
                      grow multi-measure bar support).
    - ``horizontal`` — bar charts only: render horizontally.
    - ``domain``    — extra static domain ANDed with the search filters.
    """

    title: str
    chart: Literal["bar", "line", "pie"]
    stacked: bool
    horizontal: bool
    domain: list


class _ArchPivotRequired(TypedDict):
    # Row groupby specs (innermost group last). At least one required;
    # `[]` would degenerate into a 1-row table.
    row_groupby: list[str]
    # Column groupby specs. Empty list means a single measure column
    # per measure entry — a flat "category vs measure" matrix.
    col_groupby: list[str]
    # Measure specs — same syntax as ``ArchGraph.measure``. Multiple
    # measures stack as extra columns within each leaf-col group.
    measures: list[str]


class ArchPivot(_ArchPivotRequired, total=False):
    """Arch for ``view_type="pivot"`` views.

    Required: ``row_groupby``, ``col_groupby``, ``measures``. Optional:

    - ``title``  — page heading.
    - ``domain`` — extra static domain ANDed with the search filters.
    """

    title: str
    domain: list


# ---- dashboard widgets -------------------------------------------

DashboardWidgetType = Literal["chart", "table", "stat", "link"]
DashboardColspan = Union[int, Literal["full"]]
ViewRef = Union[str, tuple[str, str]]


class DashboardWidget(TypedDict, total=False):
    """One tile on a ``view_type="dashboard"`` page.

    Every widget carries ``type`` and ``id`` (a stable DOM key). Other
    keys depend on the type — see the builder helpers in
    ``pyvelm.builders``.
    """

    type: DashboardWidgetType
    id: str
    title: str
    colspan: DashboardColspan
    # chart
    model: str
    groupby: str
    measure: str
    chart: Literal["bar", "line", "pie"]
    domain: list
    view: ViewRef
    # table
    fields: list[FieldRefLike]
    columns: list[str]
    limit: int
    order: str
    more_href: str
    # stat
    href: str
    # link
    subtitle: str
    description: str
    url: str


class _ArchDashboardRequired(TypedDict):
    widgets: list[DashboardWidget]


class ArchDashboard(_ArchDashboardRequired, total=False):
    """Arch for ``view_type="dashboard"`` views."""

    title: str
    subtitle: str
    columns: int


# Any view's arch must be one of these shapes (matching `view_type`).
Arch = Union[ArchList, ArchForm, ArchKanban, ArchGraph, ArchPivot, ArchDashboard]


# ---- discriminated-union view types ----
#
# Each concrete type locks ``view_type`` to a Literal and ``arch`` to
# the matching arch shape. Pyright/Pylance uses the ``view_type``
# discriminant to narrow ``arch`` automatically: once you type
# ``"view_type": "list"`` the IDE knows ``arch`` must satisfy
# ``ArchList`` and flags extra or missing keys accordingly.

class _ListViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["list"]
    arch: ArchList


class ListView(_ListViewRequired, total=False):
    """A ``view_type="list"`` view declaration."""

    priority: int


class _FormViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["form"]
    arch: ArchForm


class FormView(_FormViewRequired, total=False):
    """A ``view_type="form"`` view declaration."""

    priority: int


class _KanbanViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["kanban"]
    arch: ArchKanban


class KanbanView(_KanbanViewRequired, total=False):
    """A ``view_type="kanban"`` view declaration."""

    priority: int


class _GraphViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["graph"]
    arch: ArchGraph


class GraphView(_GraphViewRequired, total=False):
    """A ``view_type="graph"`` view declaration."""

    priority: int


class _PivotViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["pivot"]
    arch: ArchPivot


class PivotView(_PivotViewRequired, total=False):
    """A ``view_type="pivot"`` view declaration."""

    priority: int


class _DashboardViewRequired(TypedDict):
    name: str
    model: str
    view_type: Literal["dashboard"]
    arch: ArchDashboard


class DashboardView(_DashboardViewRequired, total=False):
    """A ``view_type="dashboard"`` view declaration."""

    priority: int


# Union alias kept for backwards compatibility and for lists that mix
# view types (the common case).
ViewType = Literal["list", "form", "kanban", "graph", "pivot", "dashboard"]
View = Union[ListView, FormView, KanbanView, GraphView, PivotView, DashboardView]


# ---- inheritance ops ----------------------------------------------

OpKind = Literal["set", "replace", "update", "remove", "before", "after"]

# A single ``target`` segment. The ``Literal["**"]`` alternative is
# what makes the wildcard prefix autocomplete in editors — it's only
# valid as the first element of the segment list (``apply_operations``
# enforces that at install time).
TargetSegment = Union[str, int, dict, Literal["**"]]


class _OperationRequired(TypedDict):
    op: OpKind
    target: list[TargetSegment]


class Operation(_OperationRequired, total=False):
    """One inheritance operation against a parent view's arch.

    ``target`` is a list of segments. Slice C of Stage 7 widens the
    accepted segment types:
      - ``str``  – dict-key or list-by-``name`` lookup (shorthand for
                   ``{"name": "<str>"}`` on list-of-dicts parents)
      - ``int``  – positional index on a list parent
      - ``dict`` – predicate; first list entry where every key/value
                   in the dict matches the entry's attributes
      - ``"**"`` – wildcard prefix, only valid as the first segment;
                   finds any descendant where the next segment would
                   succeed and anchors the rest of the lookup there

    ``value`` is required for every op except ``remove``. The type
    checker can't easily express "required for op != remove" so
    ``value`` stays optional here; ``apply_operations`` raises at
    install time when it's missing.
    """

    value: Any


class _ViewInheritRequired(TypedDict):
    name: str
    inherit: str                # ``"<module>.<view_name>"``
    operations: list[Operation]


class ViewInherit(_ViewInheritRequired, total=False):
    """An extension view that patches another via ``operations``."""

    priority: int


# ---- sidebar menu entries ----

class _MenuRequired(TypedDict):
    name: str
    label: str


class Menu(_MenuRequired, total=False):
    """One entry in a module's ``MENUS`` list.

    Top-level groups have an ``icon`` (Heroicons name like ``"home"`` or
    legacy inline SVG) and no ``parent`` or
    ``href``. Leaf items have a ``parent`` (``"<module>.<group_name>"``,
    e.g. ``"partners.business"`` for group ``business`` in module
    ``partners``) and an ``href`` (typically ``/web/views/<module>/<view>``).

    Prefer :class:`~pyvelm.builders.Menus` so ``parent`` and ``href`` are
    derived from short group names and view names.
    """

    icon: str
    href: str
    parent: str  # fully qualified: "<module>.<menu_name>"
    sequence: int
    access_model: str  # gate visibility on this model …
    access_perm: str   # … with this perm (default "read")
    access_policy: str  # optional policy method name for recordless gating


# ---- manifest globals ---------------------------------------------

class _ManifestRequired(TypedDict):
    NAME: str
    VERSION: tuple[int, ...]


class Manifest(_ManifestRequired, total=False):
    """Shape of a ``__pyvelm__.py`` manifest's module-level globals.

    The loader reads these as individual attributes, so a manifest
    declares them at module scope rather than building a dict named
    Manifest. This TypedDict exists for tooling that wants to
    validate a manifest as a single shape.

    Only ``NAME`` and ``VERSION`` are strictly required by the loader;
    everything else (the install hook, model package, dependencies,
    catalog metadata) has sensible defaults.
    """

    DEPENDS: list[str]
    DATA: list[str]
    MODELS_PACKAGE: str
    MIGRATIONS_PACKAGE: str
    INSTALL_HOOK: str            # dotted reference, e.g. "pkg.mod:fn"
    SYNC_HOOK: str               # runs on Apps Sync (installed, same version)
    COMMANDS: list[str]         # dotted Command classes, e.g. "pkg.cmd:MyCommand"
    # Apps catalog metadata — purely informational, drives /web/apps.
    DISPLAY_NAME: str            # human label; NAME is the technical id
    SUMMARY: str
    DESCRIPTION: str
    CATEGORY: str
    AUTHOR: str
    ICON: str                    # raw inline SVG markup
    # Optional Apps catalog visibility gate (UI only):
    CATALOG_ACCESS_MODEL: str
    CATALOG_ACCESS_PERM: str
    CATALOG_ACCESS_POLICY: str


__all__ = [
    "Arch",
    "ArchForm",
    "ArchGraph",
    "ArchKanban",
    "ArchKanbanCard",
    "ArchList",
    "ArchPivot",
    "ArchSection",
    "FieldRef",
    "FieldRefLike",
    "FormView",
    "GraphView",
    "KanbanView",
    "ListView",
    "PivotView",
    "Manifest",
    "Menu",
    "OpKind",
    "Operation",
    "TargetSegment",
    "View",
    "ViewInherit",
    "ViewType",
    "WidgetHint",
]
