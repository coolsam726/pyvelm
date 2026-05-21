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

import re
from pathlib import Path
from typing import Any, Callable

import jinja2
from markupsafe import Markup, escape

from .fields import (
    Boolean,
    Char,
    Date,
    Datetime,
    Field,
    Float,
    Integer,
    Many2many,
    Many2one,
    Monetary,
    One2many,
    Text,
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


def find_renderer(
    field: Field, hint: str | None, mode: str = "display"
) -> WidgetRenderer:
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


@widget(Date)
def _render_date(value, spec, field):
    if value is None:
        return Markup("")
    return escape(value.isoformat() if hasattr(value, "isoformat") else str(value))


@widget(Datetime)
def _render_datetime(value, spec, field):
    if value is None:
        return Markup("")
    if hasattr(value, "strftime"):
        # Minute precision is plenty for UI display.
        return escape(value.strftime("%Y-%m-%d %H:%M"))
    return escape(str(value))


def _resolve_currency(spec, field):
    """Find the currency recordset for a Monetary field's record.

    Returns ``None`` when there's no record on the spec (e.g. the empty
    row in a fresh edit screen) or when the configured currency field
    is missing or empty — callers fall back to rendering a bare number.
    """
    rec = spec.get("_record")
    if rec is None:
        return None
    ccy_name = getattr(field, "currency_field", "currency_id")
    if ccy_name not in type(rec)._fields:
        return None
    ccy = getattr(rec, ccy_name)
    return ccy or None


def _format_monetary(value, currency) -> str:
    """Render ``value`` to the precision implied by ``currency.rounding``.

    The number of fractional digits is derived from the rounding step
    (0.01 → 2 digits, 1.0 → 0 digits). Falls back to ``str(value)``
    when no currency context is available."""
    if currency is None:
        return str(value)
    step = getattr(currency, "rounding", None) or 0.01
    rounded = Monetary.round_with(value, currency)
    # Digits after the decimal point. log10-style: 0.01 → 2, 1.0 → 0.
    digits = 0
    s = step
    while s < 1 and digits < 12:
        s *= 10
        digits += 1
    return f"{rounded:.{digits}f}"


@widget(Monetary)
def _render_monetary(value, spec, field):
    if value is None:
        return Markup("")
    ccy = _resolve_currency(spec, field)
    formatted = escape(_format_monetary(float(value), ccy))
    if ccy is None:
        return formatted
    symbol = escape(ccy.symbol or ccy.code or "")
    return Markup(f"{symbol}{formatted}") if symbol else formatted


@widget(Boolean)
def _render_bool(value, spec, field):
    if value is None:
        return Markup("")
    if value:
        return Markup(
            '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold'
            ' bg-success-soft text-fg-success-strong" aria-label="true">Yes</span>'
        )
    return Markup(
        '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold'
        ' bg-neutral-tertiary text-body-subtle" aria-label="false">No</span>'
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
        f"</span>"
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
        f"</svg>"
        f"</a>"
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
        parts.append(f'<span class="{chip_cls}">{escape(_display_value(rec))}</span>')
    total = len(value)
    if total > 3:
        parts.append(f'<span class="{more_cls}">+{total - 3}</span>')
    return Markup(f'<span class="inline-flex gap-1 flex-wrap">{"".join(parts)}</span>')


def _resolve_o2m_table_fields(env, comodel_name, list_view_url):
    """Pick the field list for the inline-o2m table.

    Prefers the comodel's list view fields (so the table matches what
    users see on the standalone list page). Falls back to all stored
    scalar fields on the comodel when no list view is installed."""
    if list_view_url and "ir.ui.view" in env.registry:
        # list_view_url looks like /web/views/<module>/<name>
        parts = list_view_url.rstrip("/").split("/")
        module, view_name = parts[-2], parts[-1]
        View = env["ir.ui.view"]
        match = View.search(
            [
                ("module", "=", module),
                ("name", "=", view_name),
                ("view_type", "=", "list"),
            ],
            limit=1,
        )
        if match:
            from .views import resolve_arch

            arch = resolve_arch(match)
            return list(arch.get("fields", []))
    # Fallback: every stored scalar on the comodel.
    cls = env.registry[comodel_name]
    return [
        {"name": fname}
        for fname, f in cls._fields.items()
        if getattr(f, "is_stored", True) and not isinstance(f, (One2many, Many2many))
    ]


def _resolve_o2m_sequence(env, comodel_name, list_view_url) -> str | None:
    """Return the comodel list view's `arch["sequence"]` field (or None).

    Inline-o2m tables inherit drag-reorder from the same `sequence`
    declaration that powers standalone list views — when the comodel's
    list view declares one, the embedded table renders a drag handle
    and persists the new order through the parent's save.
    """
    if not list_view_url or "ir.ui.view" not in env.registry:
        return None
    parts = list_view_url.rstrip("/").split("/")
    module, view_name = parts[-2], parts[-1]
    match = env["ir.ui.view"].search(
        [
            ("module", "=", module),
            ("name", "=", view_name),
            ("view_type", "=", "list"),
        ],
        limit=1,
    )
    if not match:
        return None
    from .views import resolve_arch

    seq = resolve_arch(match).get("sequence")
    if not seq:
        return None
    cls = env.registry[comodel_name]
    return seq if seq in cls._fields else None


@widget(One2many, hint="table")
def _render_o2m_table(value, spec, field):
    """Inline read-only table of child records on the parent form.

    Rows link to the comodel's form view. A footer "Add" button routes
    to the comodel's form-new endpoint with the inverse-FK prefilled
    from the parent record's id."""
    env = (
        value.env
        if value
        else (spec.get("_record").env if spec.get("_record") else None)
    )
    if env is None:
        return _render_collection(value, spec, field)
    comodel = spec.get("_comodel") or field.comodel_name
    list_url = spec.get("_list_view_url")
    form_url = spec.get("_form_view_url")
    inverse = spec.get("_inverse_name") or field.inverse_name

    fields_spec = _resolve_o2m_table_fields(env, comodel, list_url)
    sequence_field = _resolve_o2m_sequence(env, comodel, list_url)
    # Build header labels from the comodel's field strings.
    co_cls = env.registry[comodel]
    header_cells = []
    for fs in fields_spec:
        f = co_cls._fields.get(fs["name"])
        label = fs.get("label") or (f.string if f else fs["name"])
        header_cells.append(escape(label))

    # Render each row's cells reusing _render_cells so widgets stay
    # consistent with the rest of the system.
    body_rows: list[str] = []
    recs = list(value)
    if sequence_field:
        recs.sort(key=lambda r: (getattr(r, sequence_field) or 0, r.id))
    for rec in recs:
        cells = _render_cells(rec, fields_spec, mode="display")
        td_cells = "".join(
            f'<td class="px-3 py-2 text-sm text-body">{c["html"]}</td>' for c in cells
        )
        href = f"{form_url}/record/{rec.id}" if form_url else None
        row_attrs = (
            f' class="hover:bg-neutral-secondary cursor-pointer transition-colors" '
            f'onclick="window.location.href={escape(repr(href))}"'
            if href
            else ' class=""'
        )
        body_rows.append(f"<tr{row_attrs}>{td_cells}</tr>")

    parent = spec.get("_record")
    add_html = ""
    if form_url and parent is not None and parent._ids and inverse:
        add_href = f"{form_url}/new?{inverse}={parent.id}"
        add_html = (
            f'<div class="mt-2 flex justify-end">'
            f'<a href="{escape(add_href)}" '
            f'class="inline-flex items-center gap-1 text-xs font-medium '
            f'text-fg-brand hover:underline">'
            f'<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" '
            f'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
            f'<path stroke-linecap="round" stroke-linejoin="round" '
            f'd="M12 4.5v15m7.5-7.5h-15"/></svg>'
            f"Add</a></div>"
        )

    header_html = "".join(
        f'<th class="px-3 py-2 text-left text-2xs font-semibold uppercase '
        f'tracking-wider text-body-subtle">{h}</th>'
        for h in header_cells
    )
    empty_html = (
        (
            '<tr><td colspan="{}" class="px-3 py-4 text-center text-xs '
            'text-body-subtle">No entries yet.</td></tr>'
        ).format(len(header_cells))
        if not body_rows
        else ""
    )

    return Markup(
        f'<div class="border border-default rounded-lg overflow-hidden">'
        f'<table class="min-w-full divide-y divide-default">'
        f'<thead class="bg-neutral-secondary"><tr>{header_html}</tr></thead>'
        f'<tbody class="divide-y divide-default">{"".join(body_rows) or empty_html}</tbody>'
        f"</table></div>{add_html}"
    )


def _o2m_child_cell_spec(env, comodel_cls, sub_name, idx_token, oname):
    """Build a spec dict for one inline-o2m cell, namespacing the input
    so the server can re-assemble it as `oname[idx][sub_name]`.

    Many2one cells are enriched with the same `_search_url` /
    `_form_view_url` data the standalone form uses, so the combobox
    renders identically inside the inline table."""
    spec = {"name": f"{oname}[{idx_token}][{sub_name}]"}
    field = comodel_cls._fields.get(sub_name)
    if isinstance(field, Many2one):
        spec["_comodel"] = field.comodel_name
        spec["_search_url"] = f"/api/m2o/search?model={field.comodel_name}"
        form_lookup = _form_view_for_model(env, field.comodel_name)
        spec["_form_view_url"] = (
            f"/web/views/{form_lookup[0]}/{form_lookup[1]}" if form_lookup else None
        )
    return spec


def _render_o2m_edit_row(
    env,
    comodel_cls,
    rec_or_none,
    idx_token,
    oname,
    fields_spec,
    sequence_field: str | None = None,
):
    """Render one editable `<tr>` of an inline-o2m table.

    `rec_or_none` is None for the blank template row (its idx is the
    placeholder `__IDX__` that the Add-button JS rewrites).

    When `sequence_field` is set, a drag-handle cell precedes the data
    cells and a hidden input carries the row's current sequence value
    (drag-drop JS rewrites it in multiples of 10 on reorder)."""
    is_new = rec_or_none is None
    op_value = "create" if is_new else "update"
    prefix = f"{oname}[{idx_token}]"

    # Hidden id (only for existing rows) + op marker.
    hidden_html = (
        f'<input type="hidden" name="{escape(prefix)}[_op]" value="{op_value}">'
    )
    if not is_new:
        hidden_html += (
            f'<input type="hidden" name="{escape(prefix)}[id]" '
            f'value="{rec_or_none.id}">'
        )
    if sequence_field:
        seq_value = (
            "" if is_new else (getattr(rec_or_none, sequence_field) or 0)
        )
        hidden_html += (
            f'<input type="hidden" data-pv-o2m-seq '
            f'name="{escape(prefix)}[{escape(sequence_field)}]" '
            f'value="{seq_value}">'
        )

    # Render each visible cell as the comodel field's edit widget.
    # Skip the sequence field when drag-reorder is active — the hidden
    # input is the source of truth and a visible edit cell with the
    # same name would collide on form-parse.
    td_cells: list[str] = []
    for fs in fields_spec:
        sub_name = fs["name"]
        if sequence_field and sub_name == sequence_field:
            continue
        sub_field = comodel_cls._fields.get(sub_name)
        if sub_field is None:
            td_cells.append('<td class="px-3 py-2"></td>')
            continue
        spec = _o2m_child_cell_spec(env, comodel_cls, sub_name, idx_token, oname)
        renderer = find_renderer(sub_field, fs.get("widget"), mode="edit")
        if is_new:
            value = (
                env[sub_field.comodel_name]
                if isinstance(sub_field, Many2one)
                else sub_field.default
            )
        else:
            value = getattr(rec_or_none, sub_name)
        td_cells.append(
            f'<td class="px-3 py-2 align-top">{renderer(value, spec, sub_field)}</td>'
        )

    # Trailing cell: delete button.
    delete_btn = (
        '<td class="px-3 py-2 align-top text-right w-8">'
        '<button type="button" data-pv-o2m-delete '
        'class="text-body-subtle hover:text-fg-danger transition-colors" '
        'aria-label="Delete row">'
        '<svg class="w-4 h-4" fill="none" stroke="currentColor" '
        'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/>'
        "</svg></button></td>"
    )

    drag_handle = ""
    if sequence_field:
        drag_handle = (
            '<td class="px-2 py-2 w-8 align-middle text-body-subtle '
            'cursor-grab select-none" data-pv-o2m-drag '
            'aria-label="Drag to reorder">'
            '<svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" '
            'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
            '<path stroke-linecap="round" stroke-linejoin="round" '
            'd="M3.75 9h16.5m-16.5 6.75h16.5"/></svg></td>'
        )

    tr_attrs = ' draggable="true"' if sequence_field else ""
    return (
        f'<tr data-pv-o2m-row class="align-top"{tr_attrs}>'
        f'<td class="hidden">{hidden_html}</td>'
        f'{drag_handle}{"".join(td_cells)}{delete_btn}</tr>'
    )


@widget(One2many, hint="table", mode="edit")
def _edit_o2m_table(value, spec, field):
    """Editable inline table: each existing child is a row of inputs,
    an "Add" button clones a template row, and per-row delete buttons
    flag rows for unlink on the parent's save.

    The parent form posts everything together; `parse_form_vals`
    harvests the namespaced `<o2m_name>[<idx>][<sub>]` keys into a
    list of (op, id, vals) commands, and the form-save endpoint
    applies them inside the parent's transaction."""
    env = (
        value.env
        if value
        else (spec.get("_record").env if spec.get("_record") else None)
    )
    if env is None:
        return _render_o2m_table(value, spec, field)
    parent = spec.get("_record")
    oname = spec["name"]
    comodel = spec.get("_comodel") or field.comodel_name
    co_cls = env.registry[comodel]
    fields_spec = _resolve_o2m_table_fields(env, comodel, spec.get("_list_view_url"))
    sequence_field = _resolve_o2m_sequence(env, comodel, spec.get("_list_view_url"))

    # Column headers + one leading drag column (when sequenced) + one
    # trailing column for the delete button. The sequence field itself
    # is omitted from the visible columns — the drag handle replaces it.
    header_cells: list[str] = []
    if sequence_field:
        header_cells.append('<th class="px-2 py-2 w-8"></th>')
    visible_specs = [
        fs for fs in fields_spec if fs["name"] != sequence_field
    ] if sequence_field else fields_spec
    for fs in visible_specs:
        f = co_cls._fields.get(fs["name"])
        label = fs.get("label") or (f.string if f else fs["name"])
        header_cells.append(
            f'<th class="px-3 py-2 text-left text-2xs font-semibold uppercase '
            f'tracking-wider text-body-subtle">{escape(label)}</th>'
        )
    header_cells.append('<th class="px-3 py-2 w-8"></th>')
    col_count = len(header_cells)

    # Existing rows — sort by sequence_field when drag-reorder is on
    # so the rendered order matches the persisted one.
    existing = list(value)
    if sequence_field:
        existing.sort(key=lambda r: (getattr(r, sequence_field) or 0, r.id))
    body_rows = [
        _render_o2m_edit_row(
            env, co_cls, rec, idx, oname, fields_spec, sequence_field
        )
        for idx, rec in enumerate(existing)
    ]
    empty_html = ""
    if not body_rows:
        empty_html = (
            f'<tr data-pv-o2m-empty><td colspan="{col_count}" '
            f'class="px-3 py-4 text-center text-xs text-body-subtle">'
            f"No entries yet.</td></tr>"
        )

    # Template row for client-side cloning.
    template_row = _render_o2m_edit_row(
        env,
        co_cls,
        None,
        "__IDX__",
        oname,
        fields_spec,
        sequence_field,
    )

    add_btn = (
        '<div class="mt-2 flex justify-end">'
        '<button type="button" data-pv-o2m-add '
        'class="inline-flex items-center gap-1 text-xs font-medium '
        'text-fg-brand hover:underline">'
        '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" '
        'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M12 4.5v15m7.5-7.5h-15"/></svg>'
        "Add row</button></div>"
    )

    next_idx = len(existing)
    drag_enabled = "true" if sequence_field else "false"
    js = (
        "<script>(function(){\n"
        "var root=document.currentScript.parentElement;\n"
        'var tbody=root.querySelector("tbody");\n'
        'var tmpl=root.querySelector("template[data-pv-o2m-template]");\n'
        'var addBtn=root.querySelector("[data-pv-o2m-add]");\n'
        "var nextIdx=parseInt(root.dataset.pvO2mNext,10);\n"
        f"var dragOn={drag_enabled};\n"
        "function renumber(){\n"
        "  if(!dragOn) return;\n"
        '  var rows=tbody.querySelectorAll("tr[data-pv-o2m-row]");\n'
        "  rows.forEach(function(tr,i){\n"
        '    if(tr.classList.contains("line-through")) return;\n'
        '    var seq=tr.querySelector("input[data-pv-o2m-seq]");\n'
        "    if(seq) seq.value=String((i+1)*10);\n"
        "  });\n"
        "}\n"
        'addBtn.addEventListener("click",function(){\n'
        "  var html=tmpl.innerHTML.replace(/__IDX__/g,String(nextIdx++));\n"
        "  var frag=document.createRange().createContextualFragment(html);\n"
        '  var emptyRow=tbody.querySelector("[data-pv-o2m-empty]");\n'
        "  if(emptyRow) emptyRow.remove();\n"
        "  tbody.appendChild(frag);\n"
        "  renumber();\n"
        "});\n"
        'root.addEventListener("click",function(e){\n'
        '  var btn=e.target.closest("[data-pv-o2m-delete]");\n'
        "  if(!btn||!root.contains(btn)) return;\n"
        '  var tr=btn.closest("tr");\n'
        "  if(!tr) return;\n"
        '  var op=tr.querySelector("input[name$=\\"[_op]\\"]");\n'
        '  if(op && op.value==="create"){ tr.remove(); renumber(); return; }\n'
        '  if(op) op.value="delete";\n'
        '  tr.classList.add("opacity-40","line-through","pointer-events-none");\n'
        "  renumber();\n"
        "});\n"
        "if(dragOn){\n"
        "  var dragged=null;\n"
        '  tbody.addEventListener("dragstart",function(e){\n'
        '    var tr=e.target.closest("tr[data-pv-o2m-row]");\n'
        "    if(!tr) return;\n"
        "    dragged=tr;\n"
        '    e.dataTransfer.effectAllowed="move";\n'
        '    tr.classList.add("opacity-50");\n'
        "  });\n"
        '  tbody.addEventListener("dragend",function(){\n'
        '    if(dragged) dragged.classList.remove("opacity-50");\n'
        "    dragged=null;\n"
        "  });\n"
        '  tbody.addEventListener("dragover",function(e){\n'
        "    if(!dragged) return;\n"
        "    e.preventDefault();\n"
        '    e.dataTransfer.dropEffect="move";\n'
        '    var tr=e.target.closest("tr[data-pv-o2m-row]");\n'
        "    if(!tr||tr===dragged) return;\n"
        "    var rect=tr.getBoundingClientRect();\n"
        "    var before=(e.clientY-rect.top)<(rect.height/2);\n"
        "    tbody.insertBefore(dragged, before?tr:tr.nextSibling);\n"
        "  });\n"
        '  tbody.addEventListener("drop",function(e){\n'
        "    if(!dragged) return;\n"
        "    e.preventDefault();\n"
        "    renumber();\n"
        "  });\n"
        "}\n"
        "})();</script>"
    )

    return Markup(
        f'<div class="border border-default rounded-lg overflow-hidden" '
        f'data-pv-o2m-root data-pv-o2m-name="{escape(oname)}" '
        f'data-pv-o2m-next="{next_idx}">'
        f'<table class="min-w-full divide-y divide-default">'
        f'<thead class="bg-neutral-secondary"><tr>{"".join(header_cells)}</tr></thead>'
        f'<tbody class="divide-y divide-default">'
        f'{"".join(body_rows) or empty_html}'
        f"</tbody></table>"
        f"<template data-pv-o2m-template>{template_row}</template>"
        f"{js}</div>{add_btn}"
    )


# ---- edit-mode widgets ----

_INPUT_CLS = (
    "block w-full px-2.5 py-2 text-sm rounded-lg "
    "bg-neutral-primary border border-default text-heading "
    "placeholder:text-body-subtle "
    "focus:outline-none focus:ring-2 focus:ring-fg-brand focus:border-fg-brand "
    "disabled:cursor-not-allowed disabled:opacity-60"
)


def _readonly_marker(spec: dict) -> str:
    return " disabled" if spec.get("readonly") else ""


def _required_marker(field) -> str:
    return " required" if getattr(field, "required", False) else ""


@widget(Char, mode="edit")
def _edit_char(value, spec, field):
    val_attr = escape(str(value)) if value is not None else ""
    placeholder = escape(field.string or spec["name"])
    return Markup(
        f'<input type="text" name="{escape(spec["name"])}" value="{val_attr}" '
        f'placeholder="{placeholder}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )


@widget(Text, mode="edit")
def _edit_textarea(value, spec, field):
    val = escape(str(value)) if value is not None else ""
    placeholder = escape(field.string or spec["name"])
    # Text fields get a resizable textarea instead of a single-line input.
    return Markup(
        f'<textarea name="{escape(spec["name"])}" rows="3" '
        f'placeholder="{placeholder}" '
        f'class="{_INPUT_CLS} resize-y"'
        f"{_readonly_marker(spec)}{_required_marker(field)}>"
        f"{val}</textarea>"
    )


@widget(Integer, mode="edit")
def _edit_integer(value, spec, field):
    val_attr = str(value) if value is not None else ""
    placeholder = escape(field.string or spec["name"])
    return Markup(
        f'<input type="number" step="1" name="{escape(spec["name"])}" '
        f'value="{val_attr}" placeholder="{placeholder}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )


@widget(Float, mode="edit")
def _edit_float(value, spec, field):
    val_attr = str(value) if value is not None else ""
    placeholder = escape(field.string or spec["name"])
    return Markup(
        f'<input type="number" step="any" name="{escape(spec["name"])}" '
        f'value="{val_attr}" placeholder="{placeholder}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )


@widget(Date, mode="edit")
def _edit_date(value, spec, field):
    val_attr = ""
    if value is not None:
        val_attr = escape(
            value.isoformat() if hasattr(value, "isoformat") else str(value)
        )
    return Markup(
        f'<input type="date" name="{escape(spec["name"])}" value="{val_attr}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )


@widget(Datetime, mode="edit")
def _edit_datetime(value, spec, field):
    val_attr = ""
    if value is not None and hasattr(value, "strftime"):
        # HTML <input type="datetime-local"> wants ISO without timezone
        # and minute precision.
        val_attr = escape(value.strftime("%Y-%m-%dT%H:%M"))
    elif value is not None:
        val_attr = escape(str(value))
    return Markup(
        f'<input type="datetime-local" name="{escape(spec["name"])}" '
        f'value="{val_attr}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )


@widget(Monetary, mode="edit")
def _edit_monetary(value, spec, field):
    ccy = _resolve_currency(spec, field)
    step_attr = "any"
    if ccy is not None:
        rounding = getattr(ccy, "rounding", None) or 0.01
        if rounding > 0:
            step_attr = str(rounding)
    val_attr = str(value) if value is not None else ""
    symbol = ccy.symbol if ccy is not None and ccy.symbol else ""
    placeholder = escape(field.string or spec["name"])
    input_html = (
        f'<input type="number" step="{step_attr}" name="{escape(spec["name"])}" '
        f'value="{val_attr}" placeholder="{placeholder}" '
        f'class="{_INPUT_CLS}"{_readonly_marker(spec)}{_required_marker(field)}>'
    )
    if not symbol:
        return Markup(input_html)
    return Markup(
        f'<div class="flex items-center gap-1">'
        f'<span class="text-body-subtle text-sm">{escape(symbol)}</span>'
        f"{input_html}</div>"
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
        f'class="w-4 h-4 rounded border-default bg-neutral-secondary '
        f'text-fg-brand checked:bg-fg-brand focus:ring-2 focus:ring-fg-brand cursor-pointer"'
        f"{_readonly_marker(spec)}>"
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
def _edit_m2m(value, spec, field):
    """Chip-editor for Many2many fields.

    Renders the partial at `widgets/m2m_input.html` which mounts the
    `pvM2m` Alpine component. Pre-populated with one chip per related
    record (id + display label). On save the form posts one
    `<input type="hidden" name="<fname>" value="<id>">` per chip plus
    an empty marker so the server-side parser can tell "cleared" from
    "not submitted".
    """
    from .web import _display_value

    initial = (
        [{"id": rec.id, "label": _display_value(rec)} for rec in value] if value else []
    )
    partial = _env.get_template("widgets/m2m_input.html")
    return Markup(
        partial.render(
            name=spec["name"],
            comodel=spec.get("_comodel") or field.comodel_name,
            search_url=spec.get("_search_url")
            or f"/api/m2o/search?model={field.comodel_name}",
            initial=initial,
            readonly=bool(spec.get("readonly")),
        )
    )


@widget(One2many, mode="edit")
def _edit_o2m_readonly(value, spec, field):
    """O2m editing requires inline child-record creation/management;
    deferred. For now show the display rendering so the field at
    least communicates its current value."""
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
            spec_copy["_search_url"] = f"/api/m2o/search?model={field.comodel_name}"
            view_lookup = _form_view_for_model(env, field.comodel_name)
            if view_lookup is not None:
                module, view_name = view_lookup
                spec_copy["_form_view_url"] = f"/web/views/{module}/{view_name}"
            else:
                spec_copy["_form_view_url"] = None
        elif isinstance(field, Many2many):
            # M2m chip editor reuses the m2o search endpoint to find
            # candidate records (it's just ILIKE-on-name).
            spec_copy["_comodel"] = field.comodel_name
            spec_copy["_search_url"] = f"/api/m2o/search?model={field.comodel_name}"
        elif isinstance(field, One2many):
            spec_copy["_comodel"] = field.comodel_name
            spec_copy["_inverse_name"] = field.inverse_name
            list_lookup = _list_view_for_model(env, field.comodel_name)
            spec_copy["_list_view_url"] = (
                f"/web/views/{list_lookup[0]}/{list_lookup[1]}" if list_lookup else None
            )
            form_lookup = _form_view_for_model(env, field.comodel_name)
            spec_copy["_form_view_url"] = (
                f"/web/views/{form_lookup[0]}/{form_lookup[1]}" if form_lookup else None
            )
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
        # Widgets that need access to sibling fields (Monetary →
        # currency_field) read the record via this private key. Kept
        # off the public spec contract so view authors can't depend
        # on it.
        spec_with_rec = {**spec, "_record": record}
        cells.append({"name": fname, "html": renderer(value, spec_with_rec, field)})
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
        out.append(
            {
                "id": record.id,
                "cells": _render_cells(record, fields_spec, mode="display"),
            }
        )
    return out


def _field_headers(model_cls, fields_spec) -> list[dict]:
    """Build the table-header list, enriched with the metadata the
    central search-bar dropdown needs to pick a per-field filter UI.

    Per-header `filter_kind`:
      - `"text"`     — Char/Text. Covered by free-text search already;
                       skipped from the Filter By submenu.
      - `"m2o"`      — Many2one. Submenu offers a searchable picker
                       backed by `/api/m2o/search?model=<comodel>`.
      - `"boolean"`  — Boolean. Submenu offers a fixed "Yes / No" pair.
      - `"none"`     — anything else (Integer, Float, …). Not exposed
                       in Slice 2.

    `group_kind` mirrors that — currently only Many2one + Boolean group
    cleanly, so only those expose Group By entries.
    """
    from .fields import Boolean, Char, Many2one, Text

    out = []
    for spec in fields_spec:
        fname = spec["name"]
        label = spec.get("label")
        field = model_cls._fields.get(fname)
        if not label and field is not None:
            label = field.string
        filter_kind = "none"
        group_kind = "none"
        comodel: str | None = None
        if isinstance(field, Many2one):
            filter_kind = "m2o"
            group_kind = "m2o"
            comodel = field.comodel_name
        elif isinstance(field, Boolean):
            filter_kind = "boolean"
            group_kind = "boolean"
        elif isinstance(field, (Char, Text)):
            filter_kind = "text"
        out.append(
            {
                "name": fname,
                "label": label or fname,
                "filter_kind": filter_kind,
                "group_kind": group_kind,
                "comodel": comodel,
            }
        )
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


_O2M_NESTED_KEY = re.compile(r"^([a-zA-Z_][\w]*)\[(\d+)\]\[([a-zA-Z_][\w]*)\]$")


def _parse_scalar(field, raw):
    """Coerce a form-submitted string to its field's Python type.

    Returns (value, error_msg | None). Caller decides whether to
    apply the value or stash the error against the field name."""
    if isinstance(field, Boolean):
        # The hidden-then-checkbox pair means callers always see a
        # last value; "on" → True, anything else → False.
        return (raw == "on", None)
    if raw in ("", None):
        if getattr(field, "required", False):
            return (None, "This field is required.")
        return (None, None)
    try:
        if isinstance(field, Integer):
            return (int(raw), None)
        if isinstance(field, Float):
            return (float(raw), None)
        if isinstance(field, Many2one):
            return (int(raw), None)
        if isinstance(field, Datetime):
            return (field.to_sql_param(raw), None)
        if isinstance(field, Date):
            return (field.to_sql_param(raw), None)
        return (raw, None)
    except (TypeError, ValueError):
        if isinstance(field, Integer):
            return (None, "Must be a whole number.")
        if isinstance(field, Float):
            return (None, "Must be a number.")
        if isinstance(field, Many2one):
            return (None, "Invalid record reference.")
        if isinstance(field, Date):
            return (None, "Must be a date (YYYY-MM-DD).")
        if isinstance(field, Datetime):
            return (None, "Must be a datetime.")
        return (None, "Invalid value.")


def harvest_o2m_commands(model_cls, form_data, env) -> tuple[dict, dict]:
    """Pull inline-O2m commands out of a flat form-data MultiDict.

    Returns ``(commands_by_field, errors)``:

    * ``commands_by_field`` maps each O2m parent field name to an
      ordered list of dicts like
      ``{"op": "create"|"update"|"delete", "id": int|None,
         "vals": {...}}``.
    * ``errors`` maps the namespaced sub-key
      (``"rate_ids[0][rate]"``) to a human-readable message, suitable
      for surfacing in a form-level banner.

    Keys not matching the nested pattern are ignored — the top-level
    ``parse_form_vals`` keeps doing its own thing for scalar fields."""
    by_field: dict[str, dict[int, dict]] = {}
    keys = list(form_data.keys()) if hasattr(form_data, "keys") else list(form_data)
    for key in keys:
        m = _O2M_NESTED_KEY.match(key)
        if not m:
            continue
        oname, idx, sub = m.group(1), int(m.group(2)), m.group(3)
        ofield = model_cls._fields.get(oname)
        if not isinstance(ofield, One2many):
            continue
        bucket = by_field.setdefault(oname, {}).setdefault(idx, {})
        bucket[sub] = form_data[key]

    commands_by_field: dict[str, list] = {}
    errors: dict[str, str] = {}
    for oname, by_idx in by_field.items():
        ofield = model_cls._fields[oname]
        co_cls = env.registry[ofield.comodel_name]
        cmds: list[dict] = []
        for idx in sorted(by_idx):
            raw = dict(by_idx[idx])
            op = raw.pop("_op", "update")
            rid_raw = raw.pop("id", None)
            try:
                rid = int(rid_raw) if rid_raw not in (None, "") else None
            except (TypeError, ValueError):
                rid = None
            if op == "delete":
                if rid is None:
                    continue
                cmds.append({"op": "delete", "id": rid, "vals": {}})
                continue
            child_vals: dict = {}
            had_error = False
            for sub_name, sub_raw in raw.items():
                sub_field = co_cls._fields.get(sub_name)
                if sub_field is None or not sub_field.is_stored:
                    continue
                value, err = _parse_scalar(sub_field, sub_raw)
                if err:
                    errors[f"{oname}[{idx}][{sub_name}]"] = err
                    had_error = True
                    continue
                child_vals[sub_name] = value
            if had_error:
                continue
            if op == "create":
                cmds.append({"op": "create", "id": None, "vals": child_vals})
            else:
                if rid is None:
                    continue
                cmds.append({"op": "update", "id": rid, "vals": child_vals})
        if cmds:
            commands_by_field[oname] = cmds
    return commands_by_field, errors


def apply_o2m_commands(parent_record, commands_by_field):
    """Persist O2m commands harvested by :func:`harvest_o2m_commands`.

    Runs inside the caller's transaction. For ``create`` commands the
    inverse FK is set to the parent record so the new child stays
    linked even when the form didn't surface that field explicitly.
    """
    env = parent_record.env
    parent_cls = type(parent_record)
    for oname, cmds in commands_by_field.items():
        ofield = parent_cls._fields[oname]
        Child = env[ofield.comodel_name]
        inverse = ofield.inverse_name
        for cmd in cmds:
            op = cmd["op"]
            if op == "create":
                vals = dict(cmd["vals"])
                vals.setdefault(inverse, parent_record.id)
                Child.create(vals)
            elif op == "update":
                Child.browse(cmd["id"]).write(cmd["vals"])
            elif op == "delete":
                Child.browse(cmd["id"]).unlink()


def parse_form_vals(model_cls, form_data) -> tuple[dict, dict]:
    """Convert a form-data MultiDict back into `(vals, errors)`.

    `vals` is the ORM-ready dict suitable for `create()` / `write()`.
    `errors` maps `field_name -> human-readable message` for any
    field that couldn't be coerced or that was left blank when
    declared `required=True`. Empty `errors` means it's safe to
    persist; non-empty means the caller should re-render the edit
    form with messages stamped on the offending cells.

    Boolean checkboxes use a hidden-input-then-checkbox pair so that
    "unchecked" produces an empty string and "checked" produces "on"
    (we take the last value via `getlist`). Many2one selects emit an
    empty string for the null option, which becomes `None`.

    Unknown form keys are ignored (the form may legitimately include
    framework-private fields). Empty Char inputs become `None` rather
    than empty strings.
    """
    vals: dict = {}
    errors: dict[str, str] = {}
    for fname, field in model_cls._fields.items():
        # Many2many: handled before the is_stored gate. M2m has no
        # column on the owning table (is_stored=False) but the chip
        # editor still posts ids that BaseModel.write turns into
        # junction-table rows.
        if isinstance(field, Many2many):
            if fname not in form_data:
                continue
            seq = (
                form_data.getlist(fname)
                if hasattr(form_data, "getlist")
                else [form_data[fname]]
            )
            try:
                ids = [int(v) for v in seq if v not in ("", None)]
            except (TypeError, ValueError):
                errors[fname] = "Invalid record reference."
                continue
            vals[fname] = ids
            continue
        if not field.is_stored:
            continue
        if fname not in form_data:
            continue
        if isinstance(field, Boolean):
            seq = (
                form_data.getlist(fname)
                if hasattr(form_data, "getlist")
                else [form_data[fname]]
            )
            last = seq[-1] if seq else ""
            vals[fname] = bool(last)
            continue
        raw = form_data[fname]
        empty = raw in ("", None)

        if empty:
            if getattr(field, "required", False):
                errors[fname] = "This field is required."
            else:
                vals[fname] = None
            continue

        try:
            if isinstance(field, Integer):
                vals[fname] = int(raw)
            elif isinstance(field, Float):
                vals[fname] = float(raw)
            elif isinstance(field, Many2one):
                vals[fname] = int(raw)
            elif isinstance(field, Datetime):
                # HTML datetime-local sends "YYYY-MM-DDTHH:MM"; the
                # field's to_sql_param accepts ISO 8601 either way.
                vals[fname] = field.to_sql_param(raw)
            elif isinstance(field, Date):
                vals[fname] = field.to_sql_param(raw)
            else:
                vals[fname] = raw
        except (TypeError, ValueError):
            if isinstance(field, Integer):
                errors[fname] = "Must be a whole number."
            elif isinstance(field, Float):
                errors[fname] = "Must be a number."
            elif isinstance(field, Many2one):
                errors[fname] = "Invalid record reference."
            elif isinstance(field, Date):
                errors[fname] = "Must be a date (YYYY-MM-DD)."
            elif isinstance(field, Datetime):
                errors[fname] = "Must be a datetime."
            else:
                errors[fname] = "Invalid value."
    return vals, errors


# ---- form view rendering ----


def _form_section_html(
    section_spec,
    record_or_none,
    env,
    model_cls,
    mode: str,
    errors: dict | None = None,
    submitted: dict | None = None,
    prefill: dict | None = None,
) -> list[dict]:
    """Build the per-field HTML for one section.

    Returns a list of cell dicts (`{name, label, required, error, html}`).

    `errors` is the `{field_name: message}` map from a previous failed
    save; `submitted` is the `vals` from that same attempt so the user
    doesn't lose what they typed in unrelated fields. Both default to
    empty.
    """
    errors = errors or {}
    submitted = submitted or {}
    prefill = prefill or {}
    fields_spec = list(section_spec.get("fields", []))
    # Spec enrichment (URLs for relationship widgets) is harmless in
    # display mode and required by the O2m table widget, so always run.
    fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    cells: list[dict] = []
    for spec in fields_spec:
        fname = spec["name"]
        if fname not in model_cls._fields:
            cells.append({"name": fname, "label": fname, "html": Markup("")})
            continue
        field = model_cls._fields[fname]
        label = spec.get("label") or field.string or fname
        hint = spec.get("widget")
        renderer = find_renderer(field, hint, mode=mode)

        if fname in submitted:
            # Resurrect the value the user just submitted so they don't
            # lose typing when one field errored. Many2one's `submitted`
            # form is an id; Many2many is a list of ids — reconstitute
            # both as recordsets so the widgets can render labels.
            raw = submitted[fname]
            if isinstance(field, Many2one):
                value = (
                    env[field.comodel_name].browse(raw)
                    if raw
                    else env[field.comodel_name]
                )
            elif isinstance(field, Many2many):
                if raw:
                    value = env[field.comodel_name].browse(tuple(raw))
                else:
                    value = env[field.comodel_name]
            else:
                value = raw
        elif record_or_none is None:
            if fname in prefill:
                raw = prefill[fname]
                if isinstance(field, Many2one):
                    value = (
                        env[field.comodel_name].browse(raw)
                        if raw
                        else env[field.comodel_name]
                    )
                else:
                    value = raw
            else:
                value = (
                    env[field.comodel_name]
                    if isinstance(field, Many2one)
                    else field.default
                )
        else:
            value = getattr(record_or_none, fname)

        spec_with_rec = {**spec, "_record": record_or_none}
        # Wide cells span both grid columns. O2m tables are full-width
        # so the embedded `<table>` isn't squished into half the form.
        is_wide = isinstance(field, One2many) and spec.get("widget") == "table"
        cells.append(
            {
                "name": fname,
                "label": label,
                "required": getattr(field, "required", False),
                "error": errors.get(fname),
                "wide": is_wide,
                "html": renderer(value, spec_with_rec, field),
            }
        )
    return cells


def _form_sections(
    view,
    record_or_none,
    env,
    mode: str,
    errors: dict | None = None,
    submitted: dict | None = None,
    prefill: dict | None = None,
) -> list[dict]:
    from .views import resolve_arch

    arch = resolve_arch(view)
    model_cls = env.registry[view.model]
    sections_spec = arch.get("sections", [])
    out: list[dict] = []
    for spec in sections_spec:
        out.append(
            {
                "name": spec.get("name"),
                "title": spec.get("title") or spec.get("name", ""),
                "cells": _form_section_html(
                    spec,
                    record_or_none,
                    env,
                    model_cls,
                    mode,
                    errors=errors,
                    submitted=submitted,
                    prefill=prefill,
                ),
            }
        )
    return out


def _humanize_model(model_name: str, plural: bool = True) -> str:
    """Convert a dotted model name to a human label.

    `res.partner`     → `Partners`   (last segment, title-cased, pluralised)
    `ir.model.access` → `Access`     (already ends in a vowel-ish, no s)
    `res.company`     → `Companies`  (y → ies)
    `res.users`       → `Users`      (already plural)
    """
    part = model_name.rsplit(".", 1)[-1].replace("_", " ")
    label = part.title()
    if plural:
        if label.endswith("s"):
            pass  # already plural
        elif label.endswith("y") and len(label) > 1:
            label = label[:-1] + "ies"
        else:
            label += "s"
    return label


def _view_title(view, arch: dict) -> str:
    """Return the human-readable page heading for a list or kanban view.

    Priority order:
      1. `title` key in the arch  (explicitly set by the view author)
      2. Humanised model name     (automatic fallback)
    """
    return arch.get("title") or _humanize_model(view.model)


def _record_title(record_or_none, view_model: str, mode: str) -> str:
    """Best-effort short title for the form header."""
    if mode == "new" or record_or_none is None:
        return f"New {_humanize_model(view_model, plural=False)}"
    cls = type(record_or_none)
    if "name" in cls._fields:
        nm = getattr(record_or_none, "name", None)
        if nm:
            return str(nm)
    return f"{view_model} #{record_or_none.id}"


def render_form_page(
    view,
    record_or_none,
    env,
    *,
    mode: str,
    body_only: bool = False,
    current_path: str | None = None,
    errors: dict | None = None,
    submitted: dict | None = None,
    form_error: str | None = None,
    prefill: dict | None = None,
) -> str:
    """Render the form HTML.

    `mode` is "display", "edit", or "new". For "new" the record is None
    and field values come from defaults. `body_only` returns just the
    swappable inner-HTML fragment (used by HTMX swap targets); the
    default returns a complete page.

    `errors` / `submitted` carry forward state from a failed save:
    `errors` stamps per-field messages, `submitted` resurrects the
    typed values so the user doesn't lose work. `form_error` is a
    top-level message for whole-form failures (e.g. ORM raised on
    write — unique constraint, database error).
    """
    sections = _form_sections(
        view,
        record_or_none,
        env,
        mode,
        errors=errors,
        submitted=submitted,
        prefill=prefill,
    )
    title = _record_title(record_or_none, view.model, mode)
    template_name = "form_body.html" if body_only else "form.html"
    template = _env.get_template(template_name)
    # The form view doesn't have a menu entry — make the breadcrumb
    # come from the model's list view's group instead, with the
    # record's title as the leaf.
    ctx = {} if body_only else layout_context(env, current_path, leaf_label=title)
    if not body_only:
        ctx["subtitle"] = f"{view.model} · {mode}"
    return template.render(
        view=view,
        record=record_or_none,
        record_id=(record_or_none.id if record_or_none else None),
        title=title,
        mode=mode,
        sections=sections,
        form_error=form_error,
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
            cards.append(
                {
                    "id": rec.id,
                    "title": (
                        _render_field_bare(rec, title_attr)
                        if title_attr
                        else Markup("")
                    ),
                    "subtitle": (
                        _render_field_bare(rec, subtitle_attr)
                        if subtitle_attr
                        else Markup("")
                    ),
                    "fields": [_render_field_label(rec, s) for s in fields_spec],
                    "badges": [_render_field_label(rec, s) for s in badges_spec],
                    "link": (
                        f"/web/views/{view.module}/{form_view}/record/{rec.id}"
                        if form_view
                        else None
                    ),
                }
            )
        columns.append(
            {
                "label": grp["label"],
                "key": grp["key"],
                "count": len(grp["records"]),
                "cards": cards,
            }
        )

    page_title = _view_title(view, arch)
    template = _env.get_template("kanban.html")
    return template.render(
        view=view,
        columns=columns,
        total=len(recs),
        page_title=page_title,
        subtitle=(
            f"{len(recs)} record{'s' if len(recs) != 1 else ''}"
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


def _list_view_for_model(env, model_name: str) -> tuple[str, str] | None:
    """Return `(module, view_name)` for some list view that targets the
    given model, or `None`. Used by the inline-O2m table widget to
    learn which fields the comodel wants to surface in a table."""
    if "ir.ui.view" not in env.registry:
        return None
    View = env["ir.ui.view"]
    matches = View.search(
        [("model", "=", model_name), ("view_type", "=", "list")],
        limit=1,
        order='"id" ASC',
    )
    if not matches:
        return None
    rec = matches
    rec.ensure_one()
    return (rec.module, rec.name)


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
    """Parse a JSON chip list into domain leaves AND-ed into the search.

    Wire format (Slice 1 of the central search bar):

        [{"field": "name", "op": "ilike", "value": "alice"},
         {"field": "country_id", "op": "=", "value": 3},
         ...]

    Allowed ops: ``ilike``, ``=``, ``!=``, ``>``, ``>=``, ``<``, ``<=``,
    ``in``. Each chip must reference a field in `fields_spec` (or
    ``id``) so users can't smuggle filters against unrelated columns;
    unknown / empty chips are silently dropped. Values are coerced
    type-aware: Char/Text get wrapped in ``%...%`` for ``ilike``,
    Many2one accepts an int id or a name substring (auto-routed
    through the comodel's ``.name`` dotted-path).

    The older ``{field: text}`` dict form is still accepted so URLs
    bookmarked before the chip migration keep working.
    """
    import json
    from .fields import Char, Many2one, Text

    if not filters:
        return []
    try:
        data = json.loads(filters)
    except (json.JSONDecodeError, TypeError):
        return []

    # Normalize: convert legacy dict form into a chip list so the
    # rest of the function only deals with one shape.
    if isinstance(data, dict):
        chips = [{"field": k, "op": "ilike", "value": v} for k, v in data.items()]
    elif isinstance(data, list):
        chips = data
    else:
        return []

    _allowed_ops = {"ilike", "=", "!=", ">", ">=", "<", "<=", "in"}
    allowed_fields = {s["name"] for s in fields_spec} | {"id"}

    leaves: list[tuple] = []
    for chip in chips:
        if not isinstance(chip, dict):
            continue
        fname = chip.get("field")
        op = chip.get("op", "ilike")
        value = chip.get("value")
        if fname not in allowed_fields or value in (None, ""):
            continue
        if op not in _allowed_ops:
            continue
        if fname == "id":
            try:
                leaves.append(("id", "=", int(value)))
            except (TypeError, ValueError):
                continue
            continue
        field = model_cls._fields.get(fname)
        if field is None:
            continue
        # Type-aware coercion. Char/Text always go through ilike
        # regardless of the requested op (so a stray "=" chip on a
        # text column still does the right thing). Many2one accepts
        # an explicit id (=) or a name substring (ilike).
        if isinstance(field, (Char, Text)):
            leaves.append((fname, "ilike", f"%{value}%"))
        elif isinstance(field, Many2one):
            if op == "=" or isinstance(value, int):
                try:
                    leaves.append((fname, "=", int(value)))
                except (TypeError, ValueError):
                    leaves.append((f"{fname}.name", "ilike", f"%{value}%"))
            else:
                try:
                    leaves.append((fname, "=", int(value)))
                except (TypeError, ValueError):
                    leaves.append((f"{fname}.name", "ilike", f"%{value}%"))
        else:
            try:
                leaves.append((fname, op, field.to_sql_param(value)))
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
    m = re.fullmatch(r"(\w+)\s+(ASC|DESC)", order.strip(), re.IGNORECASE)
    if not m:
        return '"id" ASC'
    field_name, direction = m.group(1), m.group(2).upper()
    allowed = {s["name"] for s in fields_spec} | {"id"}
    if field_name not in allowed:
        return '"id" ASC'
    return f'"{field_name}" {direction}'


def _group_rows(
    records, view, fields_spec, group_by: str, env, model_cls
) -> list[dict]:
    """Bucket `records` by their `group_by` field value.

    Returns a list of `{key, label, count, rows}` dicts, ordered by
    first appearance of each key in the source list (which is itself
    ordered by the active sort). Empty groups are omitted.

    For Many2one, the key is the related record's id and the label is
    its display value (falls back to "(none)" for NULL). For Boolean,
    the key is True/False and the label is "Yes"/"No". For everything
    else, the key is the raw value and the label is `str(value)`.
    """
    from .fields import Boolean, Many2one
    from .web import _display_value

    field = model_cls._fields.get(group_by)
    is_m2o = isinstance(field, Many2one)
    is_bool = isinstance(field, Boolean)

    buckets: dict = {}
    order: list = []
    for rec in records:
        raw = getattr(rec, group_by, None)
        if is_m2o:
            key = raw.id if raw else None
            label = _display_value(raw) if raw else "(none)"
        elif is_bool:
            key = bool(raw)
            label = "Yes" if key else "No"
        else:
            key = raw
            label = "(none)" if raw is None else str(raw)
        if key not in buckets:
            buckets[key] = {"key": key, "label": label, "count": 0, "records": []}
            order.append(key)
        buckets[key]["count"] += 1
        buckets[key]["records"].append(rec)

    groups = []
    for k in order:
        bucket = buckets[k]
        groups.append(
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "count": bucket["count"],
                "rows": _build_rows(view, bucket["records"], fields_spec),
            }
        )
    return groups


def render_list_page(
    view,
    env,
    *,
    page: int,
    page_size: int,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    current_path: str | None = None,
) -> str:
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

    # Drag-reorder: `arch["sequence"]` names the Integer field that
    # backs the row ordering. When present we force-sort by that
    # field, ignoring any user-supplied order (drag-reorder semantics
    # only make sense in the canonical order). Pagination is also
    # disabled so the user always sees the full list — reordering a
    # paginated subset would be confusing.
    sequence_field = arch.get("sequence")
    if sequence_field and sequence_field in model_cls._fields:
        safe_ord = f'"{sequence_field}" ASC, "id" ASC'
    else:
        sequence_field = None
        safe_ord = _safe_order(fields_spec, order)

    fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    headers = _field_headers(model_cls, fields_spec)
    # Validate group_by against the headers' group_kind metadata. An
    # unknown column or one whose type doesn't group cleanly is silently
    # dropped — the value is user-controlled URL input.
    safe_group_by = (
        group_by
        if any(h["name"] == group_by and h["group_kind"] != "none" for h in headers)
        else ""
    )

    total = Model.search_count(domain)
    if safe_group_by:
        # When grouping is active, fetch all matching records (capped)
        # and skip pagination — Odoo's behavior. The cap keeps memory
        # bounded if someone groups a huge table without filtering.
        _GROUP_CAP = 500
        recs = Model.search(domain, limit=_GROUP_CAP, order=safe_ord)
        groups = _group_rows(recs, view, fields_spec, safe_group_by, env, model_cls)
        rows = []
        total_pages = 1
    elif sequence_field:
        # No pagination when drag-reorder is active.
        recs = Model.search(domain, order=safe_ord)
        groups = None
        rows = _build_rows(view, recs, fields_spec)
        total_pages = 1
    else:
        offset = page * page_size
        recs = Model.search(domain, limit=page_size, offset=offset, order=safe_ord)
        groups = None
        rows = _build_rows(view, recs, fields_spec)
        total_pages = max(1, (total + page_size - 1) // page_size)

    page_title = _view_title(view, arch)
    template = _env.get_template("list.html")
    return template.render(
        view=view,
        headers=headers,
        rows=rows,
        groups=groups,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        search=search,
        order=order,
        filters=filters,
        group_by=safe_group_by,
        sequence_field=sequence_field,
        form_view_name=form_view_name,
        page_title=page_title,
        subtitle=f"{total} record{'s' if total != 1 else ''}",
        **layout_context(env, current_path),
    )


def render_list_rows(
    view,
    env,
    *,
    page: int,
    page_size: int,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
) -> str:
    """Table body fragment + oob pagination — used by HTMX control swaps."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    form_view_name = arch.get("form_view") or _find_form_view(view, env)

    model_cls = env.registry[view.model]
    Model = env[view.model]

    domain = _build_search_domain(model_cls, fields_spec, search) if search else []
    domain.extend(_parse_filters(model_cls, fields_spec, filters))

    sequence_field = arch.get("sequence")
    if sequence_field and sequence_field in model_cls._fields:
        safe_ord = f'"{sequence_field}" ASC, "id" ASC'
    else:
        sequence_field = None
        safe_ord = _safe_order(fields_spec, order)

    fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
    headers = _field_headers(model_cls, fields_spec)
    safe_group_by = (
        group_by
        if any(h["name"] == group_by and h["group_kind"] != "none" for h in headers)
        else ""
    )

    total = Model.search_count(domain)
    if safe_group_by:
        _GROUP_CAP = 500
        recs = Model.search(domain, limit=_GROUP_CAP, order=safe_ord)
        groups = _group_rows(recs, view, fields_spec, safe_group_by, env, model_cls)
        rows = []
        total_pages = 1
    elif sequence_field:
        recs = Model.search(domain, order=safe_ord)
        groups = None
        rows = _build_rows(view, recs, fields_spec)
        total_pages = 1
    else:
        offset = page * page_size
        recs = Model.search(domain, limit=page_size, offset=offset, order=safe_ord)
        groups = None
        rows = _build_rows(view, recs, fields_spec)
        total_pages = max(1, (total + page_size - 1) // page_size)

    template = _env.get_template("list_rows.html")
    return template.render(
        view=view,
        headers=headers,
        rows=rows,
        groups=groups,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        search=search,
        order=order,
        filters=filters,
        group_by=safe_group_by,
        sequence_field=sequence_field,
        form_view_name=form_view_name,
    )


def render_password_page(
    env, *, current_path: str | None = None, error: str = "", success: bool = False
) -> str:
    """Self-service password-change form. The form lives outside the
    res.users edit flow because the bcrypt verification of the
    current password belongs to the user themselves; admins can still
    set passwords on other accounts via the regular res.users form."""
    template = _env.get_template("password.html")
    return template.render(
        error=error,
        success=success,
        **layout_context(env, current_path),
    )


def render_login_page(
    *,
    error: str = "",
    next: str = "",
    prefill_login: str = "",
    csrf_token: str = "",
) -> str:
    template = _env.get_template("login.html")
    return template.render(
        error=error,
        next=next,
        prefill_login=prefill_login,
        csrf_token=csrf_token,
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


def _apps_catalog(env, module_roots: list) -> list[dict]:
    """Discover every module under `module_roots`, join with installed-
    version rows from `ir_module`, and return one dict per module.

    Each entry shape:
        {
          "name": str,
          "summary": str, "description": str, "category": str,
          "author": str, "icon": str,
          "available_version": str,
          "installed_version": str | None,
          "state": "installed" | "to_upgrade" | "uninstalled",
          "depends": list[str],
          "deps_missing": list[str],   # names of deps not yet installed
          "deps_unknown": list[str],   # subset of deps_missing that are
                                       # also absent from the on-disk
                                       # module roots — these block install
                                       # because the cascade can't pick them
                                       # up. Empty list means "cascade can
                                       # handle it."
        }
    """
    from . import loader as _loader

    specs = _loader.discover(module_roots) if module_roots else {}

    installed: dict[str, str] = {}
    try:
        rows = env.conn.execute(
            f'SELECT "name", "version" FROM "{_loader.IR_MODULE_TABLE}"'
        ).fetchall()
        installed = {n: v for n, v in rows}
    except Exception:  # noqa: BLE001
        # Fresh DB before any install — table doesn't exist yet.
        installed = {}

    catalog: list[dict] = []
    for name, spec in specs.items():
        inst = installed.get(name)
        if inst is None:
            state = "uninstalled"
        else:
            installed_v = tuple(int(p) for p in inst.split("."))
            state = "to_upgrade" if spec.version > installed_v else "installed"
        deps_missing = [d for d in spec.depends if d not in installed]
        deps_unknown = [d for d in deps_missing if d not in specs]
        catalog.append(
            {
                "name": spec.name,
                "summary": spec.summary,
                "description": spec.description,
                "category": spec.category or "Uncategorised",
                "author": spec.author,
                "icon": spec.icon,
                "available_version": spec.version_str,
                "installed_version": inst,
                "state": state,
                "depends": spec.depends,
                "deps_missing": deps_missing,
                "deps_unknown": deps_unknown,
            }
        )
    catalog.sort(key=lambda c: (c["category"], c["name"]))
    return catalog


def install_module_action(env, module_roots: list, target_name: str) -> dict:
    """Install `target_name` (and any uninstalled prerequisites) into
    the live environment + registry.

    Returns a dict describing the action: `{ok, message, installed:
    [names]}`. Raises ValueError on any unrecoverable problem (unknown
    module, dependency cycle, install hook error — the env transaction
    rolls back so partial state is impossible).
    """
    from . import loader as _loader

    specs = _loader.discover(module_roots)
    if target_name not in specs:
        raise ValueError(f"Unknown module {target_name!r}")

    # Figure out the topo-ordered list of things to install: the
    # target plus any of its (transitive) deps that aren't installed
    # yet. resolve_order topo-sorts the whole graph; we trim to the
    # frontier.
    ordered = _loader.resolve_order(specs)
    installed = set(
        r[0]
        for r in env.conn.execute(
            f'SELECT "name" FROM "{_loader.IR_MODULE_TABLE}"'
        ).fetchall()
    )

    def needed(name: str, acc: set):
        if name in installed or name in acc:
            return
        spec = specs[name]
        for d in spec.depends:
            needed(d, acc)
        acc.add(name)

    needed_set: set = set()
    needed(target_name, needed_set)
    to_install = [s for s in ordered if s.name in needed_set]

    # Import each module's Python so its models register into the
    # live registry, then run install (schema, hooks, views, menus).
    for spec in to_install:
        if not spec.loaded:
            _loader._load_models(spec, env.registry)
    _loader.install(to_install, env)

    return {
        "ok": True,
        "installed": [s.name for s in to_install],
        "message": (
            f"Installed {target_name}"
            + (f" + {len(to_install) - 1} dependencies" if len(to_install) > 1 else "")
        ),
    }


def upgrade_module_action(env, module_roots: list, target_name: str) -> dict:
    """Run the loader's install pass for an already-installed module.
    If the on-disk version exceeds the installed version, migrations
    run; either way views / menus / data files re-sync.

    Note: in-process model definitions are NOT reloaded — a new field
    declared in the upgraded version only takes effect after a
    process restart. The DB schema migration runs regardless via
    the version-gap migration files. Callers should advise users to
    restart for fresh model definitions to take effect.
    """
    from . import loader as _loader

    specs = _loader.discover(module_roots)
    if target_name not in specs:
        raise ValueError(f"Unknown module {target_name!r}")
    spec = specs[target_name]
    _loader.install([spec], env)
    return {
        "ok": True,
        "upgraded": [target_name],
        "message": f"Upgraded {target_name} to {spec.version_str}",
    }


def uninstall_preview(env, module_roots: list, target_name: str) -> dict:
    """Compute what would happen if `target_name` were uninstalled.

    Returns a dict shaped for both the JSON endpoint and the confirm
    modal. `blockers` is the list of reasons the uninstall would be
    refused; an empty list means it's safe to proceed.

    Counts cover the user-visible side effects:
      - tables: tables that would be DROP CASCADE'd
      - views / menus / access / rules: row counts in ir_* tables
    """
    from . import loader as _loader

    if target_name == "base":
        return {
            "target": target_name,
            "blockers": ["`base` is the system module and cannot be uninstalled."],
            "tables": [],
            "views": 0,
            "menus": 0,
            "access": 0,
            "rules": 0,
            "reverse_deps": [],
        }

    blockers: list[str] = []

    # Reverse dependency lookup: any installed module whose disk
    # manifest declares `target_name` in DEPENDS blocks the uninstall.
    specs = _loader.discover(module_roots) if module_roots else {}
    installed_rows = env.conn.execute(
        f'SELECT "name" FROM "{_loader.IR_MODULE_TABLE}"'
    ).fetchall()
    installed = {r[0] for r in installed_rows}
    reverse_deps = []
    for n in installed:
        if n == target_name:
            continue
        s = specs.get(n)
        if s and target_name in s.depends:
            reverse_deps.append(n)
    if reverse_deps:
        blockers.append(f"Still depended on by: {', '.join(sorted(reverse_deps))}")

    # Modules that extend other models via _inherit aren't safely
    # reversible today — the new columns sit on tables owned by
    # other modules and we don't track per-module column ownership.
    registry = env.registry
    extends = list(registry._model_extensions.get(target_name, []))
    if extends:
        blockers.append(
            f"Extends models via _inherit: {', '.join(sorted(extends))}. "
            f"Uninstall would orphan their added columns."
        )

    # Tables owned by this module.
    owned_tables: list[str] = []
    for model_name, owner in registry._model_module.items():
        if owner == target_name:
            cls = registry._models.get(model_name)
            if cls is not None:
                owned_tables.append(cls._table)

    # Counts of data rows we'd clean up. Each module's identity in
    # ir.ui.view / ir.ui.menu is `module = <target_name>`.
    def _count(table: str, where: str = '"module" = %s') -> int:
        try:
            row = env.conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE {where}',
                [target_name],
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001
            return 0

    return {
        "target": target_name,
        "blockers": blockers,
        "tables": sorted(owned_tables),
        "views": _count("ir_ui_view"),
        "menus": _count("ir_ui_menu"),
        # ir.model.access / ir.rule entries are seeded by install hooks
        # using "<group>/<model>"-style names; we don't track which
        # module owns each one, so report 0 and let them linger. Same
        # constraint Odoo lives with for very old data files.
        "access": 0,
        "rules": 0,
        "reverse_deps": sorted(reverse_deps),
    }


def uninstall_module_action(env, module_roots: list, target_name: str) -> dict:
    """Drop tables, delete view/menu records, and remove the ir_module
    row for `target_name`. Refuses to proceed if `uninstall_preview`
    returns blockers — that's the single safety gate.

    Side effects are all wrapped in one transaction so a mid-flight
    failure rolls everything back.
    """
    preview = uninstall_preview(env, module_roots, target_name)
    if preview["blockers"]:
        raise ValueError("; ".join(preview["blockers"]))

    with env.transaction():
        for table in preview["tables"]:
            env.conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
        env.conn.execute('DELETE FROM "ir_ui_view" WHERE "module" = %s', [target_name])
        env.conn.execute('DELETE FROM "ir_ui_menu" WHERE "module" = %s', [target_name])
        env.conn.execute('DELETE FROM "ir_module" WHERE "name" = %s', [target_name])
        # Forget the module's models from the live registry so future
        # /web/apps catalog passes show it as Not installed.
        registry = env.registry
        forgotten = [
            mn
            for mn, owner in list(registry._model_module.items())
            if owner == target_name
        ]
        for mn in forgotten:
            registry._model_module.pop(mn, None)
            registry._models.pop(mn, None)

    return {
        "ok": True,
        "uninstalled": target_name,
        "message": f"Uninstalled {target_name}",
    }


def render_apps_page(env, module_roots: list, current_path: str | None = None) -> str:
    """Read-only Apps catalog at `/web/apps`. Slice 2 adds the install /
    upgrade actions on top of the same template."""
    catalog = _apps_catalog(env, module_roots)
    summary = {
        "total": len(catalog),
        "installed": sum(1 for c in catalog if c["state"] == "installed"),
        "to_upgrade": sum(1 for c in catalog if c["state"] == "to_upgrade"),
        "uninstalled": sum(1 for c in catalog if c["state"] == "uninstalled"),
    }
    template = _env.get_template("apps.html")
    return template.render(
        catalog=catalog,
        summary=summary,
        page_title="Apps",
        subtitle=(
            f"{summary['total']} modules · "
            f"{summary['installed']} installed · "
            f"{summary['to_upgrade']} to upgrade · "
            f"{summary['uninstalled']} uninstalled"
        ),
        **layout_context(env, current_path),
    )


STATIC_DIR = Path(__file__).parent / "static"


# ---- shared layout context ----------------------------------------------
#
# Every full-page render (list / form / kanban / admin) extends
# `layouts/main.html`, which expects a stable bundle of "who am I /
# what are my apps / what are my companies" data plus the menu tree.
# `layout_context(env, current_path=None)` produces that bundle so
# individual renderers don't have to re-build it.


def _menu(env, current_path: str | None) -> list[dict]:
    """Build the sidebar menu tree from `ir.ui.menu`.

    Each installed module contributes entries via its `MENUS` data
    file; the loader upserts them keyed by `(module, name)`. Here we
    walk the table once, group by parent, and emit a two-level tree
    sorted by (sequence, label). ACL is bypassed because menus are
    system metadata: every authenticated session needs the same view
    of the navigation, regardless of group membership.
    """
    if "ir.ui.menu" not in env.registry:
        return []

    def _mark(item: dict) -> dict:
        href = item.get("href")
        active = bool(
            href
            and current_path
            and (current_path == href or current_path.startswith(href + "/"))
        )
        item["active"] = active
        for child in item.get("children", []) or []:
            _mark(child)
            if child.get("active"):
                item["active"] = True
        return item

    prev = env._acl_bypass
    env._acl_bypass = True
    try:
        Menu = env["ir.ui.menu"]
        records = Menu.search(
            [("active", "=", True)], order='"sequence" ASC, "label" ASC'
        )
        by_parent: dict[int | None, list[dict]] = {}
        for r in records:
            entry = {
                "label": r.label,
                "href": r.href or None,
                "icon": Markup(r.icon) if r.icon else None,
                "children": [],
            }
            parent_id = r.parent_id.id if r.parent_id else None
            by_parent.setdefault(parent_id, []).append((r.id, entry))
    finally:
        env._acl_bypass = prev

    # Stitch children onto parents.
    items: list[dict] = []
    for parent_id, group in by_parent.items():
        if parent_id is None:
            for _rid, entry in group:
                items.append(entry)
    for parent_id, children in by_parent.items():
        if parent_id is None:
            continue
        # Find the entry whose id matches parent_id.
        for top_id, top_entry in by_parent.get(None, []):
            if top_id == parent_id:
                top_entry["children"] = [c for _cid, c in children]
                break
    return [_mark(item) for item in items]


def build_breadcrumbs(
    menu_tree: list, current_path: str | None, leaf_label: str | None = None
) -> list[dict]:
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


def layout_context(
    env, current_path: str | None = None, leaf_label: str | None = None
) -> dict:
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
