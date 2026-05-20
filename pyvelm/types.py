"""Static-typing helpers for manifest and view authoring.

These exist purely so IDE-side tools (Pylance/Pyright, mypy) can flag
typos, missing required keys, and shape mismatches at edit time. They
have no runtime effect — the loader still does duck-typed reads of
each module's globals. Apps that don't use a type checker can ignore
this module entirely.

Recommended usage in a data file:

    from pyvelm.types import View, ViewInherit

    VIEWS: list[View] = [
        {
            "name": "partner.list",
            "model": "res.partner",
            "view_type": "list",
            "arch": {"fields": ["name", "code"]},
        },
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

# `NotRequired` is in typing as of 3.11+ but in typing_extensions
# earlier. We support 3.10+ via pyproject's requires-python, so use the
# typing_extensions shim for the import to stay portable.
try:
    from typing import NotRequired  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    from typing_extensions import NotRequired  # type: ignore


# ---- field references inside arch ----

class FieldRef(TypedDict, total=False):
    """One field entry inside an arch list (list.fields,
    form.sections[*].fields, kanban.card.fields, kanban.card.badges).

    Authoring sugar: a bare string `"name"` is equivalent to
    `{"name": "name"}`. The normalizer rewrites strings to dicts on
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

class ArchList(TypedDict):
    fields: list[FieldRefLike]


class ArchSection(TypedDict):
    name: str
    title: str
    fields: list[FieldRefLike]


class ArchForm(TypedDict):
    sections: list[ArchSection]


class ArchKanbanCard(TypedDict, total=False):
    title: str
    subtitle: str
    fields: list[FieldRefLike]
    badges: list[FieldRefLike]


class ArchKanban(TypedDict, total=False):
    card: ArchKanbanCard
    group_by: str
    form_view: str


# Any view's arch must be one of these shapes (matching `view_type`).
Arch = Union[ArchList, ArchForm, ArchKanban]


# ---- top-level view declarations ----

ViewType = Literal["list", "form", "kanban"]


class View(TypedDict, total=False):
    """A base view declaration. Required keys: name, model, view_type,
    arch. `priority` defaults to 16 if omitted."""

    name: str
    model: str
    view_type: ViewType
    arch: Arch
    priority: int


# ---- inheritance ops ----

OpKind = Literal["set", "replace", "update", "remove", "before", "after"]


class Operation(TypedDict, total=False):
    """One inheritance operation against a parent view's arch.

    `target` is a list of segments. Slice C of Stage 7 widens the
    accepted segment types:
      - `str`  – dict-key or list-by-`name` lookup (shorthand for
                 `{"name": "<str>"}` on list-of-dicts parents)
      - `int`  – positional index on a list parent
      - `dict` – predicate; first list entry where every key/value
                 in the dict matches the entry's attributes
      - `"**"` – wildcard prefix, only valid as the first segment;
                 finds any descendant where the next segment would
                 succeed and anchors the rest of the lookup there

    `value` is required for every op except `remove`.
    """

    op: OpKind
    target: list[Union[str, int, dict]]
    value: Any  # required except for remove; type is op-dependent


class ViewInherit(TypedDict, total=False):
    """An extension view that patches another via `operations`."""

    name: str
    inherit: str               # `<module>.<view_name>`
    priority: int
    operations: list[Operation]


# ---- manifest globals ----

class Manifest(TypedDict, total=False):
    """Shape of a `__pyvelm__.py` manifest's module-level globals.

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
    "Manifest",
    "OpKind",
    "Operation",
    "View",
    "ViewInherit",
    "ViewType",
]
