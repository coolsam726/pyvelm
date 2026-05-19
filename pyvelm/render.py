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
# Display-mode registry: (field_class, hint) -> renderer.
_registry: dict[tuple[type, str | None], WidgetRenderer] = {}
# Edit-mode registry: (field_class, hint) -> renderer. Separate so
# display-only widgets (chips, toggles) don't accidentally become
# input controls when a row enters edit mode.
_edit_registry: dict[tuple[type, str | None], WidgetRenderer] = {}


def widget(field_class: type, hint: str | None = None, mode: str = "display"):
    """Register a renderer for (field_class, hint) under `mode`.
    Decorator."""
    table = _registry if mode == "display" else _edit_registry
    def decorator(fn: WidgetRenderer) -> WidgetRenderer:
        table[(field_class, hint)] = fn
        return fn
    return decorator


def find_renderer(field: Field, hint: str | None, mode: str = "display") -> WidgetRenderer:
    """Walk the field's MRO looking for an explicit hint match; fall
    back to a no-hint match at the same level; finally return the
    default renderer for the requested mode."""
    table = _registry if mode == "display" else _edit_registry
    for cls in type(field).__mro__:
        if not isinstance(cls, type) or not issubclass(cls, Field):
            continue
        if hint is not None:
            r = table.get((cls, hint))
            if r is not None:
                return r
        r = table.get((cls, None))
        if r is not None:
            return r
    return _default_renderer if mode == "display" else _default_edit


def _default_renderer(value, spec, field):
    return escape(str(value)) if value is not None else Markup("")


def _default_edit(value, spec, field):
    """Fallback edit widget: text input."""
    val_attr = escape(str(value)) if value is not None else ""
    return Markup(
        f'<input type="text" name="{escape(spec["name"])}" value="{val_attr}" '
        f'class="border border-gray-300 rounded px-2 py-1 w-full text-sm">'
    )


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


# ---- edit-mode widgets ----

_INPUT_CLS = (
    "border border-gray-300 rounded px-2 py-1 w-full text-sm "
    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
)


def _readonly_marker(spec: dict) -> str:
    return " disabled" if spec.get("readonly") else ""


@widget(Char, mode="edit")
@widget(Text, mode="edit")
def _edit_text(value, spec, field):
    val_attr = escape(str(value)) if value is not None else ""
    return Markup(
        f'<input type="text" name="{escape(spec["name"])}" value="{val_attr}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}>'
    )


@widget(Integer, mode="edit")
def _edit_integer(value, spec, field):
    val_attr = str(value) if value is not None else ""
    return Markup(
        f'<input type="number" step="1" name="{escape(spec["name"])}" '
        f'value="{val_attr}" class="{_INPUT_CLS}"{_readonly_marker(spec)}>'
    )


@widget(Float, mode="edit")
def _edit_float(value, spec, field):
    val_attr = str(value) if value is not None else ""
    return Markup(
        f'<input type="number" step="any" name="{escape(spec["name"])}" '
        f'value="{val_attr}" class="{_INPUT_CLS}"{_readonly_marker(spec)}>'
    )


@widget(Boolean, mode="edit")
@widget(Boolean, hint="toggle", mode="edit")
def _edit_boolean(value, spec, field):
    # HTML quirk: an unchecked checkbox doesn't submit at all. To
    # detect "explicit false," ship a hidden field with the same name
    # set to "" *before* the checkbox; if the checkbox is checked,
    # browsers submit BOTH values and the checkbox's "on" wins (we
    # take the last value in form parsing).
    checked = "checked" if value else ""
    return Markup(
        f'<input type="hidden" name="{escape(spec["name"])}" value="">'
        f'<input type="checkbox" name="{escape(spec["name"])}" value="on" {checked} '
        f'class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"'
        f'{_readonly_marker(spec)}>'
    )


@widget(Many2one, mode="edit")
def _edit_m2o(value, spec, field):
    """Server-rendered <select> with all comodel records as options.

    Fine for small comodels (countries, regions). When comodel size
    grows past a few hundred, swap to an HTMX-loaded search-select —
    same `widget` hint, different renderer.
    """
    from .web import _display_value

    # `field` carries the comodel name; resolve via the descriptor's
    # env when we get hold of one. Here we don't have an env handy,
    # so we use the field's comodel hint via a thread-local set by
    # the row renderer. Simpler: stash the choices on spec.
    choices = spec.get("_choices", [])
    selected_id = value.id if value else None
    options = ['<option value="">—</option>']
    for cid, label in choices:
        sel = " selected" if cid == selected_id else ""
        options.append(
            f'<option value="{cid}"{sel}>{escape(label)}</option>'
        )
    return Markup(
        f'<select name="{escape(spec["name"])}" class="{_INPUT_CLS}"'
        f'{_readonly_marker(spec)}>{"".join(options)}</select>'
    )


@widget(Many2many, mode="edit")
@widget(One2many, mode="edit")
def _edit_collection_readonly(value, spec, field):
    """Slice B.3 doesn't ship a multi-select widget; show the display
    rendering as read-only context inside the edit row."""
    return _render_collection(value, spec, field)


# ----- Jinja environment -----

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("pyvelm", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _enrich_specs_for_edit(env, model_cls, fields_spec) -> list[dict]:
    """For each Many2one field-spec, fetch the comodel's choices once
    so the row renderer doesn't requery on every record.

    Mutates copies of the specs (caller's list is untouched). The
    enrichment lives on a `_choices` key inside each spec dict.
    """
    out = []
    for spec in fields_spec:
        spec_copy = dict(spec)
        fname = spec_copy["name"]
        field = model_cls._fields.get(fname)
        if isinstance(field, Many2one):
            comodel = env[field.comodel_name]
            recs = comodel.search([], order='"id" ASC')
            from .web import _display_value
            spec_copy["_choices"] = [(r.id, _display_value(r)) for r in recs]
        out.append(spec_copy)
    return out


def _render_cells(record, fields_spec, mode: str) -> list[dict]:
    cls = type(record)
    cells = []
    for spec in fields_spec:
        fname = spec["name"]
        if fname not in cls._fields:
            cells.append({"name": fname, "html": Markup("")})
            continue
        field = cls._fields[fname]
        hint = spec.get("widget")
        renderer = find_renderer(field, hint, mode=mode)
        value = getattr(record, fname)
        cells.append({"name": fname, "html": renderer(value, spec, field)})
    return cells


def _render_cells_empty(env, model_cls, fields_spec, mode: str) -> list[dict]:
    """Like _render_cells but for a brand-new (unsaved) record. Each
    field is rendered with its default value (or None) so the edit
    row presents empty/default inputs."""
    cells = []
    for spec in fields_spec:
        fname = spec["name"]
        if fname not in model_cls._fields:
            cells.append({"name": fname, "html": Markup("")})
            continue
        field = model_cls._fields[fname]
        hint = spec.get("widget")
        renderer = find_renderer(field, hint, mode=mode)
        # Use the field's default; for Many2one that's a sentinel for
        # "empty" so the descriptor's __get__ returns an empty recordset.
        if isinstance(field, Many2one):
            value = env[field.comodel_name]
        else:
            value = field.default
        cells.append({"name": fname, "html": renderer(value, spec, field)})
    return cells


def _build_rows(view, recordset, fields_spec) -> list[dict]:
    """For display-mode multi-row rendering."""
    out: list[dict] = []
    for record in recordset:
        out.append({
            "id": record.id,
            "cells": _render_cells(record, fields_spec, mode="display"),
        })
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


def render_list_row(view, record, env, *, mode: str = "display") -> str:
    """Render a single `<tr>` fragment for a record.

    Used by the click-to-edit flow: GET (display), GET .../edit (edit),
    POST .../row/{id} (returns display after save), POST .../new (returns
    display after create). One template per mode.
    """
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    cls = env.registry[view.model]
    if mode == "edit":
        fields_spec = _enrich_specs_for_edit(env, cls, fields_spec)
    cells = _render_cells(record, fields_spec, mode=mode)
    template_name = "list_row_edit.html" if mode == "edit" else "list_row.html"
    template = _env.get_template(template_name)
    return template.render(view=view, row={"id": record.id, "cells": cells})


def render_new_row(view, env) -> str:
    """Render an empty edit `<tr>` for inline creation."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    cls = env.registry[view.model]
    fields_spec = _enrich_specs_for_edit(env, cls, fields_spec)
    cells = _render_cells_empty(env, cls, fields_spec, mode="edit")
    template = _env.get_template("list_row_edit.html")
    return template.render(view=view, row={"id": None, "cells": cells})


def parse_form_vals(model_cls, form_data) -> dict:
    """Convert a form-data MultiDict back into ORM vals.

    Boolean checkboxes use a hidden-input-then-checkbox pair so that
    "unchecked" produces an empty string and "checked" produces "on"
    (we take the last value via `getlist`). Many2one selects emit an
    empty string for the null option, which becomes `None`.

    Unknown form keys are ignored (the form may legitimately include
    framework-private fields). Empty Char inputs become `None` rather
    than empty strings.
    """
    vals: dict = {}
    for fname, field in model_cls._fields.items():
        if not field.is_stored:
            continue
        if isinstance(field, Many2many):
            continue  # multi-select widget not in B.3
        if fname not in form_data:
            continue
        if isinstance(field, Boolean):
            # Take the last submitted value: hidden = "" then optionally
            # checkbox = "on" (or whatever value=).
            seq = form_data.getlist(fname) if hasattr(form_data, "getlist") else [form_data[fname]]
            last = seq[-1] if seq else ""
            vals[fname] = bool(last)
            continue
        raw = form_data[fname]
        if isinstance(field, Integer):
            vals[fname] = int(raw) if raw not in ("", None) else None
        elif isinstance(field, Float):
            vals[fname] = float(raw) if raw not in ("", None) else None
        elif isinstance(field, Many2one):
            vals[fname] = int(raw) if raw not in ("", None) else None
        else:
            vals[fname] = raw if raw != "" else None
    return vals


# ---- form view rendering ----

def _form_section_html(section_spec, record_or_none, env, model_cls, mode: str) -> list[dict]:
    """Build the per-field HTML for one section.

    Returns a list of cell dicts (`{name, label, html}`), one per field.
    """
    fields_spec = list(section_spec.get("fields", []))
    if mode == "edit":
        fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    cells: list[dict] = []
    for spec in fields_spec:
        fname = spec["name"]
        if fname not in model_cls._fields:
            cells.append({"name": fname, "label": fname, "html": Markup("")})
            continue
        field = model_cls._fields[fname]
        # Display label: spec override > field.string > raw attr name.
        label = spec.get("label") or field.string or fname
        hint = spec.get("widget")
        renderer = find_renderer(field, hint, mode=mode)
        if record_or_none is None:
            value = (
                env[field.comodel_name] if isinstance(field, Many2one)
                else field.default
            )
        else:
            value = getattr(record_or_none, fname)
        cells.append({
            "name": fname,
            "label": label,
            "html": renderer(value, spec, field),
        })
    return cells


def _form_sections(view, record_or_none, env, mode: str) -> list[dict]:
    from .views import resolve_arch

    arch = resolve_arch(view)
    model_cls = env.registry[view.model]
    sections_spec = arch.get("sections", [])
    out: list[dict] = []
    for spec in sections_spec:
        out.append({
            "name": spec.get("name"),
            "title": spec.get("title") or spec.get("name", ""),
            "cells": _form_section_html(spec, record_or_none, env, model_cls, mode),
        })
    return out


def _record_title(record_or_none, view_model: str, mode: str) -> str:
    """Best-effort short title for the form header."""
    if mode == "new" or record_or_none is None:
        return f"New {view_model}"
    cls = type(record_or_none)
    if "name" in cls._fields:
        nm = getattr(record_or_none, "name", None)
        if nm:
            return str(nm)
    return f"{view_model} #{record_or_none.id}"


def render_form_page(view, record_or_none, env, *, mode: str, body_only: bool = False) -> str:
    """Render the form HTML.

    `mode` is "display", "edit", or "new". For "new" the record is None
    and field values come from defaults. `body_only` returns just the
    swappable inner-HTML fragment (used by HTMX swap targets); the
    default returns a complete page.
    """
    sections = _form_sections(view, record_or_none, env, mode)
    title = _record_title(record_or_none, view.model, mode)
    template_name = "form_body.html" if body_only else "form.html"
    template = _env.get_template(template_name)
    return template.render(
        view=view,
        record=record_or_none,
        record_id=(record_or_none.id if record_or_none else None),
        title=title,
        mode=mode,
        sections=sections,
    )


# ---- kanban view rendering ----

def _render_field_label(record, spec: dict) -> dict:
    """Render one card field as `{label, html}`."""
    fname = spec["name"]
    cls = type(record)
    if fname not in cls._fields:
        return {"label": fname, "html": Markup("")}
    field = cls._fields[fname]
    label = spec.get("label") or field.string or fname
    hint = spec.get("widget")
    renderer = find_renderer(field, hint, mode="display")
    value = getattr(record, fname)
    return {"label": label, "html": renderer(value, spec, field)}


def _render_field_bare(record, fname: str) -> Markup:
    """Render the display value of a single named field (no label)."""
    cls = type(record)
    if fname not in cls._fields or fname is None:
        return Markup("")
    field = cls._fields[fname]
    renderer = find_renderer(field, None, mode="display")
    value = getattr(record, fname)
    return renderer(value, {"name": fname}, field)


def _group_records(recordset, group_by_attr: str, env) -> list[dict]:
    """Bucket recordset by group_by_attr value. Returns
    `[{key, label, records}, ...]` preserving first-seen order."""
    cls = env.registry[recordset._name]
    if group_by_attr not in cls._fields:
        raise ValueError(
            f"group_by references unknown field {group_by_attr!r} "
            f"on {recordset._name}"
        )
    field = cls._fields[group_by_attr]
    from .web import _display_value

    groups: dict = {}
    for rec in recordset:
        value = getattr(rec, group_by_attr)
        if isinstance(field, Many2one):
            key = value.id if value else None
            label = _display_value(value) if value else "(no value)"
        else:
            key = value
            label = "(no value)" if value is None else str(value)
        if key not in groups:
            groups[key] = {"key": key, "label": label, "records": []}
        groups[key]["records"].append(rec)
    return list(groups.values())


def render_kanban_page(view, env) -> str:
    """Render a kanban view: cards optionally grouped into columns.

    Arch shape:
        {"card": {"title": "<attr>", "subtitle": "<attr>",
                  "fields": [...], "badges": [...]},
         "group_by": "<attr>"  (optional),
         "form_view": "<view_name>"  (optional, makes cards clickable)}
    """
    from .views import resolve_arch

    arch = resolve_arch(view)
    card = arch.get("card", {})
    group_by = arch.get("group_by")
    form_view = arch.get("form_view")

    Model = env[view.model]
    recs = Model.search([], order='"id" ASC')

    if group_by:
        groups = _group_records(recs, group_by, env)
    else:
        groups = [{"key": None, "label": "All", "records": list(recs)}]

    title_attr = card.get("title")
    subtitle_attr = card.get("subtitle")
    fields_spec = list(card.get("fields", []))
    badges_spec = list(card.get("badges", []))

    columns = []
    for grp in groups:
        cards = []
        for rec in grp["records"]:
            cards.append({
                "id": rec.id,
                "title": _render_field_bare(rec, title_attr) if title_attr else Markup(""),
                "subtitle": _render_field_bare(rec, subtitle_attr) if subtitle_attr else Markup(""),
                "fields": [_render_field_label(rec, s) for s in fields_spec],
                "badges": [_render_field_label(rec, s) for s in badges_spec],
                "link": (
                    f"/web/views/{view.module}/{form_view}/record/{rec.id}"
                    if form_view else None
                ),
            })
        columns.append({
            "label": grp["label"],
            "key": grp["key"],
            "count": len(grp["records"]),
            "cards": cards,
        })

    template = _env.get_template("kanban.html")
    return template.render(view=view, columns=columns, total=len(recs))


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


def render_login_page(
    *,
    error: str = "",
    next: str = "",
    prefill_login: str = "",
) -> str:
    template = _env.get_template("login.html")
    return template.render(
        error=error,
        next=next,
        prefill_login=prefill_login,
    )


def render_admin_page(
    companies: list | None = None,
    current_company_id: int | None = None,
) -> str:
    cards = [
        {
            "title": "Groups",
            "subtitle": "res.groups",
            "description": "Manage permission groups and their members.",
            "url": "/web/views/admin/group.list",
        },
        {
            "title": "Users",
            "subtitle": "res.users",
            "description": "Create and manage operator accounts.",
            "url": "/web/views/admin/user.list",
        },
        {
            "title": "Access Control",
            "subtitle": "ir.model.access",
            "description": "Grant CRUD permissions per model and group.",
            "url": "/web/views/admin/access.list",
        },
        {
            "title": "Record Rules",
            "subtitle": "ir.rule",
            "description": "Define row-level security using domain filters.",
            "url": "/web/views/admin/rule.list",
        },
        {
            "title": "Companies",
            "subtitle": "res.company",
            "description": "Manage companies and multi-tenant configuration.",
            "url": "/web/views/admin/company.list",
        },
    ]
    template = _env.get_template("admin.html")
    return template.render(
        cards=cards,
        companies=companies or [],
        current_company_id=current_company_id,
    )


STATIC_DIR = Path(__file__).parent / "static"
