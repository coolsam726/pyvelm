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
        return Markup('<span class="text-body-subtle/60">&mdash;</span>')
    # Use the same display-value rule as the JSON serializer.
    from .web import _display_value
    label = escape(_display_value(value))
    # When the spec was enriched with the comodel's form-view URL,
    # wrap the label in a quiet inline link with a small "open"
    # affordance — same UX as the edit-mode combobox's arrow icon.
    form_view_url = spec.get("_form_view_url")
    if not form_view_url:
        return label
    href = f"{form_view_url}/record/{value.id}"
    return Markup(
        f'<a href="{href}" '
        f'class="inline-flex items-center gap-1 group/m2o '
        f'text-body hover:text-fg-brand transition-colors">'
        f'<span class="truncate">{label}</span>'
        f'<svg class="w-3 h-3 opacity-0 group-hover/m2o:opacity-100 transition-opacity" '
        f'fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5'
        f'A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/>'
        f'</svg>'
        f'</a>'
    )


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
    """Searchable combobox with create-on-the-fly + open-record link.

    The actual markup lives in `widgets/m2o_input.html`; this widget
    just hands off the spec data it was enriched with at render time
    (see `_enrich_specs_for_edit`).
    """
    from .web import _display_value

    initial_id = value.id if value else None
    initial_label = _display_value(value) if value else ""
    partial = _env.get_template("widgets/m2o_input.html")
    return Markup(
        partial.render(
            name=spec["name"],
            comodel=spec.get("_comodel") or field.comodel_name,
            search_url=spec.get("_search_url")
                       or f"/api/m2o/search?model={field.comodel_name}",
            form_view_url=spec.get("_form_view_url"),
            initial_id=initial_id,
            initial_label=initial_label,
            readonly=bool(spec.get("readonly")),
        )
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
    """For each Many2one field-spec, stash the data the combobox widget
    needs without re-resolving it per row:

      _comodel        — the comodel name string
      _form_view_url  — base URL for "Open record" / "Create and edit"
                        ("/web/views/<module>/<view_name>") or None if
                        no form view targets the comodel yet
      _search_url     — "/api/m2o/search?model=..." (built once)

    Same enrichment runs for display-mode rendering too — the
    `_form_view_url` powers the inline "open record" link next to a
    rendered Many2one value, harmless when no widget needs it.

    Mutates a copy of each spec; caller's list is untouched.
    """
    out = []
    for spec in fields_spec:
        spec_copy = dict(spec)
        fname = spec_copy["name"]
        field = model_cls._fields.get(fname)
        if isinstance(field, Many2one):
            spec_copy["_comodel"] = field.comodel_name
            spec_copy["_search_url"] = (
                f"/api/m2o/search?model={field.comodel_name}"
            )
            view_lookup = _form_view_for_model(env, field.comodel_name)
            if view_lookup is not None:
                module, view_name = view_lookup
                spec_copy["_form_view_url"] = (
                    f"/web/views/{module}/{view_name}"
                )
            else:
                spec_copy["_form_view_url"] = None
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
    # Enrich for both modes so the display-mode "open record" link
    # under each Many2one gets its URL.
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


def render_form_page(view, record_or_none, env, *, mode: str, body_only: bool = False,
                     current_path: str | None = None) -> str:
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
    # The form view doesn't have a menu entry — make the breadcrumb
    # come from the model's list view's group instead, with the
    # record's title as the leaf.
    ctx = (
        {} if body_only
        else layout_context(env, current_path, leaf_label=title)
    )
    if not body_only:
        ctx["subtitle"] = f"{view.model} · {mode}"
    return template.render(
        view=view,
        record=record_or_none,
        record_id=(record_or_none.id if record_or_none else None),
        title=title,
        mode=mode,
        sections=sections,
        **ctx,
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


def render_kanban_page(view, env, *, current_path: str | None = None) -> str:
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
    return template.render(
        view=view,
        columns=columns,
        total=len(recs),
        subtitle=(
            f"{view.model} · {len(recs)} record{'s' if len(recs) != 1 else ''}"
            f" · {len(columns)} column{'s' if len(columns) != 1 else ''}"
        ),
        **layout_context(env, current_path),
    )


def _find_form_view(view, env):
    """Return the name of the first form view for the same model+module,
    or None if no such view is registered."""
    if "ir.ui.view" not in env.registry:
        return None
    View = env["ir.ui.view"]
    matches = View.search(
        [("model", "=", view.model), ("view_type", "=", "form")],
        limit=1,
        order='"id" ASC',
    )
    if matches:
        for m in matches:
            return m.name
    return None


def _form_view_for_model(env, model_name: str) -> tuple[str, str] | None:
    """Return `(module, view_name)` for some form view that targets the
    given model, or `None` if no such view is installed.

    Used by relationship widgets to build "Open record" /
    "Create and edit" URLs without each widget having to know which
    module owns the comodel's UI.
    """
    if "ir.ui.view" not in env.registry:
        return None
    View = env["ir.ui.view"]
    matches = View.search(
        [("model", "=", model_name), ("view_type", "=", "form")],
        limit=1,
        order='"id" ASC',
    )
    if not matches:
        return None
    rec = matches
    rec.ensure_one()
    return (rec.module, rec.name)


_SEARCHABLE_FIELD_TYPES = ("Char", "Text")


def _parse_filters(model_cls, fields_spec: list, filters: str) -> list:
    """Parse a JSON dict of `{field_name: search_text}` into ilike
    domain leaves AND-ed into the search.

    Each entry must reference a field in `fields_spec` (or `id`) so
    users can't smuggle filters against unrelated columns. Unknown
    keys are silently dropped. Empty values are dropped (so an empty
    filter input doesn't constrain anything).
    """
    import json
    from .fields import Char, Many2one, Text

    if not filters:
        return []
    try:
        data = json.loads(filters)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    allowed = {s["name"] for s in fields_spec} | {"id"}
    leaves: list[tuple] = []
    for fname, term in data.items():
        if fname not in allowed or not term:
            continue
        if fname == "id":
            try:
                leaves.append(("id", "=", int(term)))
            except (TypeError, ValueError):
                continue
            continue
        field = model_cls._fields.get(fname)
        if field is None:
            continue
        # Per-field type-aware filter:
        #   text fields -> ilike '%term%'
        #   Many2one    -> ilike against the comodel's display text via
        #                  dotted-path on `name` (most comodels have it)
        #   anything else with a stored column -> = with a coerced value
        if isinstance(field, (Char, Text)):
            leaves.append((fname, "ilike", f"%{term}%"))
        elif isinstance(field, Many2one):
            # Match the comodel's `name` field via dotted-path ilike if
            # the term is non-numeric; fall back to an id match when it
            # parses as an int (so "1" matches the record with id=1).
            try:
                leaves.append((fname, "=", int(term)))
            except (TypeError, ValueError):
                leaves.append((f"{fname}.name", "ilike", f"%{term}%"))
        else:
            try:
                leaves.append((fname, "=", field.to_sql_param(term)))
            except Exception:  # noqa: BLE001
                continue
    return leaves


def _build_search_domain(model_cls, fields_spec: list, search: str) -> list:
    """Return a domain list that OR-searches `search` across all Char/Text
    fields present in `fields_spec`.  Falls back to searching on any Char/Text
    field on the model if none of the visible fields are searchable."""
    from .fields import Char, Text

    term = f"%{search}%"
    candidates: list[tuple] = []
    visible_names = {s["name"] for s in fields_spec}

    for fname, field in model_cls._fields.items():
        if isinstance(field, (Char, Text)) and field.is_stored:
            if fname in visible_names:
                candidates.append((fname, "ilike", term))

    if not candidates:
        # Fallback: any stored Char/Text on the model
        for fname, field in model_cls._fields.items():
            if isinstance(field, (Char, Text)) and field.is_stored:
                candidates.append((fname, "ilike", term))

    if not candidates:
        return []  # Model has no text fields; search returns everything
    return [("__or__", "ilike", candidates)]


_SAFE_ORDER_RE = None


def _safe_order(fields_spec: list, order: str) -> str:
    """Validate and return the SQL ORDER BY clause, or the default 'id ASC'.

    Accepts: 'field ASC', 'field DESC' where field is one of the listed
    fields or 'id'.
    """
    import re
    if not order:
        return '"id" ASC'
    m = re.fullmatch(r'(\w+)\s+(ASC|DESC)', order.strip(), re.IGNORECASE)
    if not m:
        return '"id" ASC'
    field_name, direction = m.group(1), m.group(2).upper()
    allowed = {s["name"] for s in fields_spec} | {"id"}
    if field_name not in allowed:
        return '"id" ASC'
    return f'"{field_name}" {direction}'


def render_list_page(view, env, *, page: int, page_size: int,
                     search: str = "", order: str = "", filters: str = "",
                     current_path: str | None = None) -> str:
    """Full HTML page for a list view: heading, toolbar, sortable DataTable
    with server-side search / ordering / pagination."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    form_view_name = arch.get("form_view") or _find_form_view(view, env)

    model_cls = env.registry[view.model]
    Model = env[view.model]

    domain = _build_search_domain(model_cls, fields_spec, search) if search else []
    domain.extend(_parse_filters(model_cls, fields_spec, filters))
    safe_ord = _safe_order(fields_spec, order)

    total = Model.search_count(domain)
    offset = page * page_size
    recs = Model.search(domain, limit=page_size, offset=offset, order=safe_ord)
    # Enrich specs so the display-mode Many2one widget can render an
    # "open record" affordance pointing at the comodel's form view.
    fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    rows = _build_rows(view, recs, fields_spec)
    headers = _field_headers(model_cls, fields_spec)
    total_pages = max(1, (total + page_size - 1) // page_size)

    template = _env.get_template("list.html")
    return template.render(
        view=view,
        headers=headers,
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        search=search,
        order=order,
        filters=filters,
        form_view_name=form_view_name,
        # Subtitle line shown below the title in the heading region.
        subtitle=f"{view.model} · {total} record{'s' if total != 1 else ''}",
        # `breadcrumbs` comes from layout_context; the menu-derived
        # default is correct for list views (they have a menu entry).
        **layout_context(env, current_path),
    )


def render_list_rows(view, env, *, page: int, page_size: int, search: str = "", order: str = "", filters: str = "") -> str:
    """Table body fragment + oob pagination — used by HTMX control swaps."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    form_view_name = arch.get("form_view") or _find_form_view(view, env)

    model_cls = env.registry[view.model]
    Model = env[view.model]

    domain = _build_search_domain(model_cls, fields_spec, search) if search else []
    domain.extend(_parse_filters(model_cls, fields_spec, filters))
    safe_ord = _safe_order(fields_spec, order)

    total = Model.search_count(domain)
    offset = page * page_size
    recs = Model.search(domain, limit=page_size, offset=offset, order=safe_ord)
    fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    rows = _build_rows(view, recs, fields_spec)
    headers = _field_headers(model_cls, fields_spec)
    total_pages = max(1, (total + page_size - 1) // page_size)

    template = _env.get_template("list_rows.html")
    return template.render(
        view=view,
        headers=headers,
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        search=search,
        order=order,
        filters=filters,
        form_view_name=form_view_name,
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


def render_admin_page(env=None, current_path: str | None = None) -> str:
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
        {
            "title": "Partners",
            "subtitle": "res.partner",
            "description": "Browse and manage partners for the current company.",
            "url": "/web/views/partners/partner.list",
        },
    ]
    template = _env.get_template("admin.html")
    ctx = layout_context(env, current_path) if env is not None else {}
    if env is not None:
        ctx["subtitle"] = "Framework configuration and security."
    return template.render(cards=cards, **ctx)


STATIC_DIR = Path(__file__).parent / "static"


# ---- shared layout context ----------------------------------------------
#
# Every full-page render (list / form / kanban / admin) extends
# `layouts/main.html`, which expects a stable bundle of "who am I /
# what are my apps / what are my companies" data plus the menu tree.
# `layout_context(env, current_path=None)` produces that bundle so
# individual renderers don't have to re-build it.

# Tiny inline-SVG icon set. Heroicons-style (outline, 24×24). Each is
# a Markup string so Jinja's `| safe` filter is unnecessary in templates.
_ICONS: dict[str, Markup] = {
    "home": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M2.25 12L12 2.25 21.75 12M4.5 9.75v10.125c0 .621.504 1.125 '
        '1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h4.25c.621 '
        '0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h7.5"/></svg>'
    ),
    "grid": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 '
        '2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 '
        '2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 '
        '01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 '
        '0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 '
        '10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 '
        '0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 '
        '0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z"/></svg>'
    ),
    "users": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 '
        '004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 '
        '19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 '
        '6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 '
        '2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>'
    ),
    "tag": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 '
        '9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 '
        '3.66A2.25 2.25 0 009.568 3z"/><path stroke-linecap="round" stroke-linejoin="round" d="M6 6h.008v.008H6V6z"/></svg>'
    ),
    "shield": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9 12.75L11.25 15 15 9.75M21 12c0 1.268-.63 2.39-1.593 3.068a3.745 '
        '3.745 0 01-1.043 3.296 3.745 3.745 0 01-3.296 1.043A3.745 3.745 0 0112 21c-1.268 '
        '0-2.39-.63-3.068-1.593a3.746 3.746 0 01-3.296-1.043 3.745 3.745 0 '
        '01-1.043-3.296A3.745 3.745 0 013 12c0-1.268.63-2.39 1.593-3.068a3.745 3.745 '
        '0 011.043-3.296 3.746 3.746 0 013.296-1.043A3.746 3.746 0 0112 3c1.268 0 2.39.63 '
        '3.068 1.593a3.746 3.746 0 013.296 1.043 3.746 3.746 0 011.043 3.296A3.745 3.745 0 0121 12z"/></svg>'
    ),
    "settings": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 '
        '1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 '
        '1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 '
        '0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 '
        '1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 '
        '6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 '
        '0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 '
        '01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 '
        '1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 '
        '1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 '
        '1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28z"/>'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>'
    ),
    "workflow": Markup(
        '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"/></svg>'
    ),
}


def _menu(env, current_path: str | None) -> list[dict]:
    """Build the sidebar menu tree.

    Hard-coded for now — the natural follow-up is an `ir.ui.menu` model
    with module-shipped data so apps can extend the navigation just
    like they extend views.
    """

    def _mark(item: dict) -> dict:
        href = item.get("href")
        active = bool(href and current_path and (
            current_path == href or current_path.startswith(href + "/")
        ))
        item["active"] = active
        for child in item.get("children", []) or []:
            _mark(child)
            if child.get("active"):
                item["active"] = True
        return item

    items: list[dict] = [
        {
            "label": "Dashboard",
            "href": "/web/admin",
            "icon": _ICONS["home"],
        },
        {
            "label": "CRM",
            "icon": _ICONS["workflow"],
            "children": [
                {"label": "Pipeline", "href": "/web/views/crm/lead.kanban"},
                {"label": "All Leads", "href": "/web/views/crm/lead.list"},
            ],
        },
        {
            "label": "Apps",
            "icon": _ICONS["grid"],
            "children": [
                {"label": "Partners", "href": "/web/views/partners/partner.list"},
                {"label": "Partner board", "href": "/web/views/partners/partner.kanban"},
            ],
        },
        {
            "label": "Settings",
            "icon": _ICONS["settings"],
            "children": [
                {"label": "Users", "href": "/web/views/admin/user.list"},
                {"label": "Groups", "href": "/web/views/admin/group.list"},
                {"label": "Companies", "href": "/web/views/admin/company.list"},
                {"label": "Tags", "href": "/web/views/admin/tag.list"},
            ],
        },
        {
            "label": "Security",
            "icon": _ICONS["shield"],
            "children": [
                {"label": "Model access", "href": "/web/views/admin/access.list"},
                {"label": "Record rules", "href": "/web/views/admin/rule.list"},
            ],
        },
        {
            "label": "Workflows",
            "icon": _ICONS["workflow"],
            "children": [
                {"label": "Server actions", "href": "/web/views/admin/action.list"},
                {"label": "Automation", "href": "/web/views/admin/automation.list"},
                {"label": "Cron jobs", "href": "/web/views/admin/cron.list"},
                {"label": "Messages", "href": "/web/views/admin/message.list"},
            ],
        },
    ]
    return [_mark(item) for item in items]


def build_breadcrumbs(menu_tree: list, current_path: str | None,
                      leaf_label: str | None = None) -> list[dict]:
    """Derive crumbs from the menu structure.

    Walks the menu looking for a child whose `href` matches `current_path`.
    Returns `[{"label", "href"}, ...]` with "Home" + parent-group label +
    leaf label. The leaf is overridable (e.g. `Alice` instead of
    `partner.form` on a form page).

    Always starts with a "Home" entry pointing at /web/admin so the user
    has a way back regardless of menu depth.
    """
    crumbs: list[dict] = [{"label": "Home", "href": "/web/admin"}]
    parent: dict | None = None
    leaf: dict | None = None
    if current_path:
        for group in menu_tree:
            # A flat link.
            if group.get("href") == current_path:
                leaf = group
                break
            # A children group — look one level down.
            for child in group.get("children", []) or []:
                if child.get("href") == current_path:
                    parent = group
                    leaf = child
                    break
            if leaf is not None:
                break
    if parent is not None:
        crumbs.append({"label": parent["label"], "href": None})
    if leaf is not None:
        crumbs.append({"label": leaf_label or leaf["label"], "href": None})
    elif leaf_label:
        # Path isn't in the menu but the caller knows the label.
        crumbs.append({"label": leaf_label, "href": None})
    return crumbs


def layout_context(env, current_path: str | None = None,
                   leaf_label: str | None = None) -> dict:
    """Return the shell context every page renderer passes to the
    `layouts/main.html` base template."""
    name = ""
    login = ""
    initial = "?"
    if env.uid is not None and "res.users" in env.registry:
        prev = env._acl_bypass
        env._acl_bypass = True
        try:
            user = env["res.users"].browse(env.uid)
            if env["res.users"].search([("id", "=", env.uid)]):
                name = user.name or user.login or f"user#{user.id}"
                login = user.login or ""
                initial = (name[:1] or "?").upper()
        finally:
            env._acl_bypass = prev

    companies: list[dict] = []
    current_company_name = ""
    if "res.company" in env.registry:
        bypass_env = env.with_company(None)
        bypass_env._acl_bypass = True
        try:
            for c in bypass_env["res.company"].search([]):
                companies.append({"id": c.id, "name": c.name})
                if env.company_id == c.id:
                    current_company_name = c.name
        finally:
            bypass_env._acl_bypass = False

    menu_tree = _menu(env, current_path)
    return {
        "menu": menu_tree,
        "current_user_name": name,
        "current_user_login": login,
        "current_user_initial": initial,
        "companies": companies,
        "current_company_id": env.company_id,
        "current_company_name": current_company_name,
        # Default crumbs derived from the menu. Pages that want a
        # different leaf label (e.g. the record name on a form view)
        # pass `leaf_label`; renderers can override `breadcrumbs`
        # directly when the page lives outside the menu altogether.
        "breadcrumbs": build_breadcrumbs(menu_tree, current_path, leaf_label),
    }
