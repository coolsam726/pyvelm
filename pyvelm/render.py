"""HTMX + Jinja renderer.

A small, framework-shipped UI layer that interprets `ir.ui.view.arch`
into HTML. Developers don't write Jinja — they declare view arch in
their manifests, and the framework's templates dispatch through a
widget registry to produce field HTML per cell.

The widget registry is keyed by `(field_class, hint)`:
- An explicit `widget` attribute on a field-spec dict picks a named
  variant (e.g. Boolean + "toggle" → render as a styled toggle).
- Without a hint, the registry falls back to the bare field class
  (Boolean → checkmark, Many2one → display value, etc.).
- Subclass lookup via MRO so `Text` falls through to `Char`.

Widgets are tiny functions: `(value, field_spec, field) -> Markup`.
They MUST return a `markupsafe.Markup` to opt out of Jinja auto-escape;
bare strings are escaped. This is the safety contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import jinja2
from markupsafe import Markup, escape

from .fields import (
    Boolean, Char, Field, Float, Integer,
    Many2many, Many2one, One2many, Text,
)


WidgetRenderer = Callable[[Any, dict, Field], Markup]
_registry: dict[tuple[type, str | None], WidgetRenderer] = {}


def widget(field_class: type, hint: str | None = None):
    """Register a renderer for (field_class, hint). Decorator."""
    def decorator(fn: WidgetRenderer) -> WidgetRenderer:
        _registry[(field_class, hint)] = fn
        return fn
    return decorator


def find_renderer(field: Field, hint: str | None) -> WidgetRenderer:
    """Walk the field's MRO looking for an explicit hint match; fall
    back to a no-hint match at the same level; finally return the
    default renderer."""
    for cls in type(field).__mro__:
        if not isinstance(cls, type) or not issubclass(cls, Field):
            continue
        if hint is not None:
            r = _registry.get((cls, hint))
            if r is not None:
                return r
        r = _registry.get((cls, None))
        if r is not None:
            return r
    return _default_renderer


def _default_renderer(value, spec, field):
    return escape(str(value)) if value is not None else Markup("")


@widget(Char)
@widget(Text)
def _render_text(value, spec, field):
    return escape(str(value)) if value is not None else Markup("")


@widget(Integer)
@widget(Float)
def _render_number(value, spec, field):
    return Markup("") if value is None else escape(str(value))


@widget(Boolean)
def _render_bool(value, spec, field):
    if value is None:
        return Markup("")
    if value:
        return Markup(
            '<span class="text-green-600 font-bold" aria-label="true">&#10003;</span>'
        )
    return Markup(
        '<span class="text-gray-400 font-bold" aria-label="false">&#10007;</span>'
    )


@widget(Boolean, hint="toggle")
def _render_toggle(value, spec, field):
    if value:
        track = "bg-green-500"
        knob_pos = "left-4"
        label = "on"
    else:
        track = "bg-gray-300"
        knob_pos = "left-0.5"
        label = "off"
    return Markup(
        f'<span class="relative inline-block align-middle w-8 h-4 rounded-full {track}" '
        f'role="img" aria-label="{label}">'
        f'<span class="absolute top-0.5 {knob_pos} w-3 h-3 bg-white rounded-full transition-all"></span>'
        f'</span>'
    )


@widget(Many2one)
def _render_m2o(value, spec, field):
    if not value:
        return Markup('<span class="text-gray-300">&mdash;</span>')
    # Use the same display-value rule as the JSON serializer.
    from .web import _display_value
    return escape(_display_value(value))


@widget(Many2many)
@widget(One2many)
def _render_collection(value, spec, field):
    if not value:
        return Markup('<span class="text-gray-300">&mdash;</span>')
    from .web import _display_value
    parts: list[str] = []
    chip_cls = (
        "inline-flex items-center bg-gray-100 text-gray-700 "
        "px-2 py-0.5 rounded-full text-xs"
    )
    more_cls = (
        "inline-flex items-center bg-white border border-dashed "
        "border-gray-300 text-gray-500 px-2 py-0.5 rounded-full text-xs"
    )
    for rec in list(value)[:3]:
        parts.append(
            f'<span class="{chip_cls}">{escape(_display_value(rec))}</span>'
        )
    total = len(value)
    if total > 3:
        parts.append(f'<span class="{more_cls}">+{total - 3}</span>')
    return Markup(
        f'<span class="inline-flex gap-1 flex-wrap">{"".join(parts)}</span>'
    )


# ----- Jinja environment -----

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("pyvelm", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _build_rows(view, recordset, fields_spec) -> list[dict]:
    """For each record produce a row dict the template can render.

    cells[i] is `{"name": ..., "label": ..., "html": Markup(...)}`.
    """
    model_cls = type(recordset) if recordset else None
    out: list[dict] = []
    for record in recordset:
        cls = type(record)
        cells = []
        for spec in fields_spec:
            fname = spec["name"]
            if fname not in cls._fields:
                # Field referenced by the view doesn't exist on the
                # model — render an empty cell rather than 500-ing.
                cells.append({"name": fname, "html": Markup("")})
                continue
            field = cls._fields[fname]
            hint = spec.get("widget")
            renderer = find_renderer(field, hint)
            value = getattr(record, fname)
            cells.append({"name": fname, "html": renderer(value, spec, field)})
        out.append({"id": record.id, "cells": cells})
    return out


def _field_headers(model_cls, fields_spec) -> list[dict]:
    out = []
    for spec in fields_spec:
        fname = spec["name"]
        label = spec.get("label")
        if not label and fname in model_cls._fields:
            label = model_cls._fields[fname].string
        out.append({"name": fname, "label": label or fname})
    return out


def render_list_page(view, env, *, page: int, page_size: int) -> str:
    """Full HTML page for a list view: head, table shell, first page
    of rows, and an HTMX 'load more' button if there's more."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])

    Model = env[view.model]
    total = Model.search_count([])
    offset = page * page_size
    recs = Model.search(
        [], limit=page_size, offset=offset, order='"id" ASC',
    )
    rows = _build_rows(view, recs, fields_spec)
    headers = _field_headers(env.registry[view.model], fields_spec)
    has_more = offset + len(recs) < total
    template = _env.get_template("list.html")
    return template.render(
        view=view,
        headers=headers,
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        has_more=has_more,
    )


def render_list_rows(view, env, *, page: int, page_size: int) -> str:
    """Just the <tr> fragments — used by HTMX swap-append on
    'load more' clicks."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    Model = env[view.model]
    total = Model.search_count([])
    offset = page * page_size
    recs = Model.search(
        [], limit=page_size, offset=offset, order='"id" ASC',
    )
    rows = _build_rows(view, recs, fields_spec)
    has_more = offset + len(recs) < total
    template = _env.get_template("list_rows.html")
    return template.render(
        view=view,
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        has_more=has_more,
    )


STATIC_DIR = Path(__file__).parent / "static"
