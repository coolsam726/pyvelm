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


# ---- field references inside arch ----

class FieldRef(TypedDict, total=False):
    """One field entry inside an arch list (list.fields,
    form.sections[*].fields, kanban.card.fields, kanban.card.badges).

    Authoring sugar: a bare string ``"name"`` is equivalent to
    ``{"name": "name"}``. The normalizer rewrites strings to dicts on
    storage so inheritance has stable addresses.
    """

    name: str
    widget: str
    label: str
    readonly: bool
    # Extra app-specific attributes are allowed; total=False keeps the
    # TypedDict open to additional keys without complaining.


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
    - ``sequence``  — name of an integer field; when set the renderer
                      adds a drag handle and forces sort by that field.
    """

    title: str
    form_view: str
    sequence: str


class ArchSection(TypedDict):
    name: str
    title: str
    fields: list[FieldRefLike]


class _ArchFormRequired(TypedDict):
    sections: list[ArchSection]


class ArchForm(_ArchFormRequired, total=False):
    """Arch for ``view_type="form"`` views.

    Only ``sections`` is required. Optional key:

    - ``title`` — overrides the auto-generated page heading.
    """

    title: str


class ArchKanbanCard(TypedDict, total=False):
    title: str
    subtitle: str
    fields: list[FieldRefLike]
    badges: list[FieldRefLike]


class ArchKanban(TypedDict, total=False):
    """Arch for ``view_type="kanban"`` views. All keys are optional."""

    title: str
    card: ArchKanbanCard
    group_by: str
    form_view: str


# Any view's arch must be one of these shapes (matching `view_type`).
Arch = Union[ArchList, ArchForm, ArchKanban]


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


# Union alias kept for backwards compatibility and for lists that mix
# view types (the common case).
ViewType = Literal["list", "form", "kanban"]
View = Union[ListView, FormView, KanbanView]


# ---- inheritance ops ----

OpKind = Literal["set", "replace", "update", "remove", "before", "after"]


class Operation(TypedDict, total=False):
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

    ``value`` is required for every op except ``remove``.
    """

    op: OpKind
    target: list[Union[str, int, dict]]
    value: Any  # required except for remove; type is op-dependent


class ViewInherit(TypedDict, total=False):
    """An extension view that patches another via ``operations``."""

    name: str
    inherit: str               # `<module>.<view_name>`
    priority: int
    operations: list[Operation]


# ---- sidebar menu entries ----

class _MenuRequired(TypedDict):
    name: str
    label: str


class Menu(_MenuRequired, total=False):
    """One entry in a module's ``MENUS`` list.

    Top-level groups have an ``icon`` (SVG string) and no ``parent`` or
    ``href``. Leaf items have a ``parent`` (``"<module>.<name>"``) and
    an ``href``, and no ``icon``.
    """

    icon: str
    href: str
    parent: str
    sequence: int


# ---- manifest globals ----

class Manifest(TypedDict, total=False):
    """Shape of a ``__pyvelm__.py`` manifest's module-level globals.

    The loader reads these as individual attributes, so a manifest
    declares them at module scope rather than building a dict named
    Manifest. This TypedDict exists for tooling that wants to
    validate a manifest as a single shape.
    """

    NAME: str
    VERSION: tuple[int, ...]
    DEPENDS: list[str]
    DATA: list[str]
    MODELS_PACKAGE: str
    MIGRATIONS_PACKAGE: str
    INSTALL_HOOK: str          # dotted reference, e.g. "pkg.mod:fn"


__all__ = [
    "Arch",
    "ArchForm",
    "ArchKanban",
    "ArchKanbanCard",
    "ArchList",
    "ArchSection",
    "FieldRef",
    "FieldRefLike",
    "FormView",
    "KanbanView",
    "ListView",
    "Manifest",
    "Menu",
    "OpKind",
    "Operation",
    "View",
    "ViewInherit",
    "ViewType",
]
