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

import base64
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jinja2
from markupsafe import Markup, escape

from .security import template_access
from .fields import (
    Boolean,
    Char,
    Code,
    Date,
    Datetime,
    Field,
    Float,
    Html,
    Integer,
    Many2many,
    Many2one,
    Monetary,
    One2many,
    Text,
    Time,
    spec_readonly,
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


_UTC = ZoneInfo("UTC")


def _active_tz(env) -> ZoneInfo:
    """Resolve the active company's timezone, falling back to UTC.

    Reads ``env.context['company_id']`` (the same scope used for
    company-scoped ACL). Bad / missing values silently fall back to
    UTC — the render layer never raises on a localization failure.
    """
    if env is None or "res.company" not in env.registry:
        return _UTC
    cid = env.company_id
    if cid is None:
        # No company in context: try whichever company the user belongs
        # to. With many users this is fine — they all share their
        # company's tz — and with the framework's single-company seed
        # it's the obvious right answer.
        if env.uid and "res.users" in env.registry:
            try:
                env.prime_current_user_cache()
                user = env["res.users"].browse(env.uid)
                cid = user.company_id.id if user.company_id else None
            except Exception:
                cid = None
    if cid is None:
        return _UTC
    try:
        co = env["res.company"].browse(cid)
        tz_name = (co.timezone or "").strip() or "UTC"
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, Exception):
        return _UTC


def _spec_env(spec):
    """Pull the env off a widget spec. Set by `_render_cells` /
    `_render_cells_empty` / inline-o2m so widgets that need to localize
    or look up sibling records have access without parameter churn."""
    env = spec.get("_env")
    if env is not None:
        return env
    rec = spec.get("_record")
    return rec.env if rec is not None else None


def _utc_to_local(value, env) -> datetime | None:
    """Treat a naive UTC datetime as UTC and shift to the active tz.

    Aware datetimes are converted directly. Returns None for None.
    """
    if value is None:
        return None
    if not hasattr(value, "tzinfo"):
        return value  # not a datetime — leave it for str() fallback
    aware = value if value.tzinfo is not None else value.replace(tzinfo=_UTC)
    return aware.astimezone(_active_tz(env))


@widget(Datetime)
def _render_datetime(value, spec, field):
    if value is None:
        return Markup("")
    if hasattr(value, "strftime"):
        local = _utc_to_local(value, _spec_env(spec)) or value
        # Minute precision is plenty for UI display.
        return escape(local.strftime("%Y-%m-%d %H:%M"))
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
    # Avoid `value.id` (descriptor) since Many2one targets may be unreadable
    # (we still want to render a label, but the related model ACL can deny).
    target_id = None
    try:
        target_id = value._ids[0] if getattr(value, "_ids", None) else None
    except Exception:  # noqa: BLE001
        target_id = None
    href = f"{form_view_url}/record/{target_id or value.id}"
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


def _relational_widget(spec: dict) -> str | None:
    """Normalize ``widget`` for O2m/M2m field specs."""
    w = spec.get("widget")
    if w == "table":
        return "inline"
    return w


def _o2m_use_inline_edit(spec: dict) -> bool:
    """Editable inline table on the parent form (``widget="inline"``)."""
    return _relational_widget(spec) in ("inline", "table")


def _o2m_show_table(spec: dict) -> bool:
    """Read-only table of related rows (dialog opens on click)."""
    w = _relational_widget(spec)
    if w == "inline":
        return True
    if w == "dialog":
        return bool(spec.get("_form_view_url"))
    # Default: dialog table when a comodel form exists; else chips.
    return bool(spec.get("_form_view_url"))


def _m2m_use_dialog_editor(spec: dict) -> bool:
    """Chip list + dialog create/edit; no inline typeahead search."""
    w = _relational_widget(spec)
    if w == "inline":
        return False
    if w == "dialog":
        return True
    return bool(spec.get("_form_view_url"))


def _render_m2m_chips(value, spec, field, *, max_visible: int = 3) -> Markup:
    """Render Many2many values as chips, optionally linked to form views."""
    if not value:
        return Markup('<span class="text-body-subtle/60">&mdash;</span>')
    from .web import _display_value

    form_url = spec.get("_form_view_url")
    chip_cls = (
        "inline-flex items-center gap-1 bg-brand-soft text-fg-brand "
        "px-2 py-0.5 rounded-full text-xs font-medium"
    )
    link_cls = chip_cls + " hover:underline"
    more_cls = (
        "inline-flex items-center bg-neutral-secondary border border-dashed "
        "border-default text-body-subtle px-2 py-0.5 rounded-full text-xs"
    )
    parts: list[str] = []
    recs = list(value)
    for rec in recs[:max_visible]:
        label = escape(_display_value(rec))
        if form_url:
            href = f"{form_url}/record/{rec.id}"
            parts.append(
                f'<a href="{escape(href)}" class="{link_cls}">{label}</a>'
            )
        else:
            parts.append(f'<span class="{chip_cls}">{label}</span>')
    if len(recs) > max_visible:
        parts.append(f'<span class="{more_cls}">+{len(recs) - max_visible}</span>')
    return Markup(f'<span class="inline-flex gap-1 flex-wrap">{"".join(parts)}</span>')


@widget(Many2many)
def _render_m2m_display(value, spec, field):
    return _render_m2m_chips(value, spec, field)


@widget(One2many)
def _render_collection(value, spec, field):
    if not value:
        return Markup('<span class="text-body-subtle/60">&mdash;</span>')
    from .web import _display_value

    parts: list[str] = []
    chip_cls = (
        "inline-flex items-center bg-neutral-secondary text-body "
        "px-2 py-0.5 rounded-full text-xs"
    )
    more_cls = (
        "inline-flex items-center bg-neutral-secondary border border-dashed "
        "border-default text-body-subtle px-2 py-0.5 rounded-full text-xs"
    )
    for rec in list(value)[:3]:
        parts.append(f'<span class="{chip_cls}">{escape(_display_value(rec))}</span>')
    total = len(value)
    if total > 3:
        parts.append(f'<span class="{more_cls}">+{total - 3}</span>')
    return Markup(f'<span class="inline-flex gap-1 flex-wrap">{"".join(parts)}</span>')


@widget(One2many)
def _render_o2m_field(value, spec, field):
    """Display-mode O2m: table (dialog on row click) or chips."""
    if _o2m_show_table(spec):
        return _render_o2m_table(value, spec, field)
    return _render_collection(value, spec, field)


def _filter_o2m_table_fields(env, comodel_name, fields_spec: list) -> list:
    """Drop relational columns that don't work in a compact inline row.

    Many2many chip editors and nested One2many tables need full form
    width — including them here breaks layout and save parsing."""
    cls = env.registry[comodel_name]
    out: list = []
    for fs in fields_spec:
        spec = fs if isinstance(fs, dict) else {"name": fs}
        fname = spec.get("name")
        if not fname:
            continue
        f = cls._fields.get(fname)
        if f is None or isinstance(f, (Many2many, One2many)):
            continue
        out.append(spec)
    return out


def _resolve_o2m_table_fields(env, comodel_name, list_view_url):
    """Pick the field list for the inline-o2m table.

    Prefers the comodel's list view fields (so the table matches what
    users see on the standalone list page). Falls back to all stored
    scalar fields on the comodel when no list view is installed."""
    if list_view_url and "ir.ui.view" in env.registry:
        # list_view_url looks like /web/views/<module>/<name>
        parts = list_view_url.rstrip("/").split("/")
        module, view_name = parts[-2], parts[-1]
        match = _search_ui_views(
            env,
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
            return _filter_o2m_table_fields(
                env, comodel_name, list(arch.get("fields", []))
            )
    # Fallback: every stored scalar on the comodel.
    cls = env.registry[comodel_name]
    return _filter_o2m_table_fields(
        env,
        comodel_name,
        [
            {"name": fname}
            for fname, f in cls._fields.items()
            if getattr(f, "is_stored", True)
            and not isinstance(f, (One2many, Many2many))
        ],
    )


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
    match = _search_ui_views(
        env,
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
    # Display-mode o2m rows and the "+ Add" button open the comodel's
    # form inside the global floating dialog (alternative to inline
    # editing). The `data-pv-dialog` attribute is handled by the
    # delegated click listener in layouts/main.html — it loads `href`
    # into the dialog body, and `data-pv-dialog-refresh` opts into a
    # re-fetch of the host form's shell once the save succeeds so the
    # table re-renders with the freshly-edited / created child row.
    # No fallback navigation is needed: the click handler runs before
    # the browser follows the link.
    for rec in recs:
        cells = _render_cells(rec, fields_spec, mode="display")
        td_cells = "".join(
            f'<td class="px-3 py-2 text-sm text-body">{c["html"]}</td>' for c in cells
        )
        href = f"{form_url}/record/{rec.id}" if form_url else None
        if href:
            row_attrs = (
                f' class="hover:bg-neutral-secondary cursor-pointer transition-colors"'
                f' data-pv-dialog data-pv-dialog-refresh'
                f' data-pv-dialog-title="Edit"'
                f' data-pv-dialog-url="{escape(href)}"'
            )
        else:
            row_attrs = ' class=""'
        body_rows.append(f"<tr{row_attrs}>{td_cells}</tr>")

    parent = spec.get("_record")
    add_html = ""
    if form_url and parent is not None and parent._ids and inverse:
        add_href = f"{form_url}/new?{inverse}={parent.id}"
        add_html = (
            f'<div class="mt-2 flex justify-end">'
            f'<a href="{escape(add_href)}" '
            f'data-pv-dialog data-pv-dialog-refresh '
            f'data-pv-dialog-title="New" '
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
    spec = {"name": f"{oname}[{idx_token}][{sub_name}]", "_env": env}
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
    *,
    forced_op: str | None = None,
    errors: dict | None = None,
):
    """Render one editable `<tr>` of an inline-o2m table.

    `rec_or_none` is None for the blank template row (its idx is the
    placeholder `__IDX__` that the Add-button JS rewrites).

    When `sequence_field` is set, a drag-handle cell precedes the data
    cells and a hidden input carries the row's current sequence value
    (drag-drop JS rewrites it in multiples of 10 on reorder)."""
    is_new = rec_or_none is None
    op_value = forced_op or ("create" if is_new else "update")
    is_deleted = op_value == "delete"
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
            raw = (
                env[sub_field.comodel_name]
                if isinstance(sub_field, Many2one)
                else sub_field.default
            )
        else:
            raw = getattr(rec_or_none, sub_name)
        value = _value_for_widget(env, sub_field, raw)
        err_key = f"{oname}[{idx_token}][{sub_name}]"
        cell_err = (errors or {}).get(err_key)
        err_cls = (
            " ring-2 ring-fg-danger/50 rounded-lg" if cell_err else ""
        )
        err_title = (
            f' title="{escape(cell_err)}"' if cell_err else ""
        )
        cell_html = str(renderer(value, spec, sub_field))
        if not td_cells:
            cell_html = hidden_html + cell_html
        td_cells.append(
            f'<td class="px-3 py-2 align-top{err_cls}"{err_title}>'
            f"{cell_html}</td>"
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

    tr_attrs = ' draggable="true"' if sequence_field and not is_deleted else ""
    del_cls = (
        ' class="align-top opacity-40 line-through pointer-events-none"'
        if is_deleted
        else ' class="align-top"'
    )
    if not td_cells:
        td_cells.append(
            f'<td class="px-3 py-2 align-top">{hidden_html}</td>'
        )
    return (
        f'<tr data-pv-o2m-row{del_cls}{tr_attrs}>'
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
    cell_errors = spec.get("_o2m_errors") or {}
    form_playback = spec.get("_form_playback")

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

    # Existing rows — after a failed save, replay the posted form so
    # the user doesn't lose edits; otherwise read from the recordset.
    if form_playback is not None:
        playback = _o2m_playback_rows(form_playback, oname, co_cls, env)
        body_rows = [
            _render_o2m_edit_row(
                env,
                co_cls,
                row_view,
                idx,
                oname,
                fields_spec,
                sequence_field,
                forced_op=op,
                errors=cell_errors,
            )
            for idx, row_view, op in playback
        ]
        next_idx = max((idx for idx, _, _ in playback), default=-1) + 1
    else:
        existing = list(value)
        if sequence_field:
            existing.sort(key=lambda r: (getattr(r, sequence_field) or 0, r.id))
        body_rows = [
            _render_o2m_edit_row(
                env,
                co_cls,
                rec,
                idx,
                oname,
                fields_spec,
                sequence_field,
                errors=cell_errors,
            )
            for idx, rec in enumerate(existing)
        ]
        next_idx = len(existing)
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
        errors=cell_errors,
    )

    # Odoo-style "Add a line" footer row — click anywhere on it to
    # append a new editable row (same handler as the Add row button).
    add_line_row = (
        f'<tr data-pv-o2m-add-row tabindex="0" role="button" '
        f'class="cursor-pointer hover:bg-brand-soft/30 transition-colors">'
        f'<td colspan="{col_count}" class="px-3 py-2.5 text-center text-xs '
        f'text-fg-brand font-medium">'
        f'<span class="inline-flex items-center gap-1">'
        f'<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" '
        f'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M12 4.5v15m7.5-7.5h-15"/></svg>'
        f"Add a line</span></td></tr>"
    )

    drag_enabled = "true" if sequence_field else "false"
    js = (
        "<script>(function(){\n"
        "var root=document.currentScript.parentElement;\n"
        'var tbody=root.querySelector("tbody");\n'
        'var tmpl=root.querySelector("template[data-pv-o2m-template]");\n'
        'var addLineRow=root.querySelector("[data-pv-o2m-add-row]");\n'
        "var nextIdx=parseInt(root.dataset.pvO2mNext,10)||0;\n"
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
        "function rewriteIdx(node,idx){\n"
        "  if(!node||node.nodeType!==1) return;\n"
        '  ["name","id","for"].forEach(function(a){\n'
        "    if(!node.hasAttribute(a)) return;\n"
        '    var v=node.getAttribute(a);\n'
        '    if(v.indexOf("__IDX__")>=0) node.setAttribute(a,v.split("__IDX__").join(idx));\n'
        "  });\n"
        '  if(node.hasAttribute("x-data")){\n'
        '    var xd=node.getAttribute("x-data");\n'
        '    if(xd.indexOf("__IDX__")>=0) node.setAttribute("x-data",xd.split("__IDX__").join(idx));\n'
        "  }\n"
        "  for(var i=0;i<node.children.length;i++) rewriteIdx(node.children[i],idx);\n"
        "}\n"
        "function addRow(){\n"
        "  if(!tmpl||!tmpl.content||!tmpl.content.firstElementChild) return;\n"
        "  var idx=String(nextIdx++);\n"
        "  root.dataset.pvO2mNext=String(nextIdx);\n"
        "  var row=tmpl.content.firstElementChild.cloneNode(true);\n"
        "  rewriteIdx(row,idx);\n"
        '  var emptyRow=tbody.querySelector("[data-pv-o2m-empty]");\n'
        "  if(emptyRow) emptyRow.remove();\n"
        "  if(addLineRow) tbody.insertBefore(row, addLineRow);\n"
        "  else tbody.appendChild(row);\n"
        "  if(window.Alpine&&typeof window.Alpine.initTree===\"function\") window.Alpine.initTree(row);\n"
        "  renumber();\n"
        "  var first=row.querySelector('input:not([type=hidden]),select,textarea');\n"
        "  if(first) first.focus();\n"
        "}\n"
        'root.addEventListener("click",function(e){\n'
        '  if(e.target.closest("[data-pv-o2m-add]")||e.target.closest("[data-pv-o2m-add-row]")){\n'
        "    e.preventDefault();\n"
        "    addRow();\n"
        "    return;\n"
        "  }\n"
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
        f'<div class="border border-default rounded-lg overflow-visible" '
        f'data-pv-o2m-root data-pv-o2m-name="{escape(oname)}" '
        f'data-pv-o2m-next="{next_idx}">'
        f'<table class="min-w-full divide-y divide-default">'
        f'<thead class="bg-neutral-secondary"><tr>{"".join(header_cells)}</tr></thead>'
        f'<tbody class="divide-y divide-default">'
        f'{"".join(body_rows) or empty_html}'
        f"{add_line_row}"
        f"</tbody></table>"
        f"<template data-pv-o2m-template>{template_row}</template>"
        f'<div class="px-3 py-1.5 border-t border-default bg-neutral-secondary/50 '
        f'flex justify-end">'
        f'<button type="button" data-pv-o2m-add '
        f'class="inline-flex items-center gap-1 text-xs font-medium '
        f'text-fg-brand hover:underline">'
        f'<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" '
        f'viewBox="0 0 24 24" stroke-width="2" aria-hidden="true">'
        f'<path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M12 4.5v15m7.5-7.5h-15"/></svg>'
        f"Add row</button></div>"
        f"{js}</div>"
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


@widget(Char, hint="model")
def _display_char_model(value, spec, field):
    val = str(value) if value is not None else ""
    if not val:
        return Markup("")
    env = spec.get("_env")
    if env and val in env.registry:
        cls = env.registry[val]
        label = getattr(cls, "_description", None) or val
        return Markup(
            f'<span class="font-medium">{escape(label)}</span> '
            f'<span class="text-xs text-body-subtle font-mono">{escape(val)}</span>'
        )
    return escape(val)


@widget(Char, hint="model", mode="edit")
def _edit_char_model(value, spec, field):
    val_str = str(value) if value is not None else ""
    initial_label = val_str
    env = spec.get("_env")
    if env and val_str and val_str in env.registry:
        cls = env.registry[val_str]
        initial_label = getattr(cls, "_description", None) or val_str
    partial = _env.get_template("widgets/combo_input.html")
    return Markup(
        partial.render(
            name=spec["name"],
            options=[],
            value=val_str,
            initial_label=initial_label,
            placeholder=field.string or "Select model…",
            readonly=bool(spec.get("readonly")),
            hint=val_str,
            allow_clear=not field.required,
            models_url="/api/mail/templates/models",
        )
    )


@widget(Char, mode="edit")
def _edit_char(value, spec, field):
    val_str = str(value) if value is not None else ""
    if getattr(field, "choices", None):
        options = [{"value": v, "label": l} for v, l in field.choices]
        initial_label = next(
            (lbl for val, lbl in field.choices if val_str == val), val_str
        )
        partial = _env.get_template("widgets/combo_input.html")
        return Markup(
            partial.render(
                name=spec["name"],
                options=options,
                value=val_str,
                initial_label=initial_label,
                placeholder=field.string or "Select…",
                readonly=bool(spec.get("readonly")),
                hint="",
                allow_clear=not field.required,
            )
        )
    val_attr = escape(val_str)
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


def _render_html_editor_widget(value, spec, *, readonly: bool) -> Markup:
    """Rich HTML editor with Write / Source / Preview tabs.

    The display-mode rendering reuses this same component so the
    detail page can show the record-aware live preview, not just the
    stored HTML. ``subject`` is carried in the config because the
    detail page has no form input the editor could read from.
    """
    partial = _env.get_template("widgets/html_editor.html")
    raw = "" if value is None else str(value)
    mail_model = ""
    subject = ""
    record = spec.get("_record")
    if record is not None:
        if getattr(record, "model", None):
            mail_model = str(record.model)
        if getattr(record, "subject", None):
            subject = str(record.subject)
    # Base64 in a data attribute — HTML/JSON must not live inside x-data
    # (embedded `"` in the template body truncates the attribute).
    payload = json.dumps(
        {
            "name": spec["name"],
            "initial": raw,
            "readonly": readonly,
            "mailModel": mail_model,
            "subject": subject,
        }
    ).encode()
    config_b64 = base64.b64encode(payload).decode("ascii")
    return Markup(
        partial.render(name=spec["name"], config_b64=escape(config_b64))
    )


@widget(Text, hint="html")
@widget(Html)
def _render_html_body(value, spec, field):
    return _render_html_editor_widget(value, spec, readonly=True)


@widget(Text, hint="html", mode="edit")
@widget(Html, mode="edit")
def _edit_html_body(value, spec, field):
    if spec.get("readonly"):
        return _render_html_editor_widget(value, spec, readonly=True)
    return _render_html_editor_widget(value, spec, readonly=False)


def _code_language(spec, field) -> str:
    """Per-view ``language`` wins; else the field's declared language;
    else plain text. Unknown values fall back to plain text rather
    than failing the render."""
    declared = getattr(field, "language", None) or "text"
    override = spec.get("language")
    lang = (override or declared or "text").lower()
    if lang not in Code.SUPPORTED_LANGUAGES:
        lang = "text"
    return lang


def _render_code_editor_widget(value, spec, field, *, readonly: bool) -> Markup:
    """CodeMirror 6 source editor with VSCode-like highlighting.

    The Alpine component (``pvCodeEditor``) reads its config from a
    base64 ``data-pv-config`` attribute — the same trick the HTML
    editor uses to keep JSON safely outside the ``x-data`` expression.
    """
    partial = _env.get_template("widgets/code_editor.html")
    raw = "" if value is None else str(value)
    payload = json.dumps(
        {
            "name": spec["name"],
            "initial": raw,
            "language": _code_language(spec, field),
            "readonly": readonly,
        }
    ).encode()
    config_b64 = base64.b64encode(payload).decode("ascii")
    return Markup(
        partial.render(
            name=spec["name"],
            config_b64=escape(config_b64),
            readonly=readonly,
            language=_code_language(spec, field),
            raw=raw,
        )
    )


@widget(Text, hint="code")
@widget(Code)
def _render_code_body(value, spec, field):
    return _render_code_editor_widget(value, spec, field, readonly=True)


@widget(Text, hint="code", mode="edit")
@widget(Code, mode="edit")
def _edit_code_body(value, spec, field):
    if spec.get("readonly"):
        return _render_code_editor_widget(value, spec, field, readonly=True)
    return _render_code_editor_widget(value, spec, field, readonly=False)


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
    from pyvelm.widgets.datetime_pickers import render_date_picker

    return render_date_picker(value, spec, field)


@widget(Datetime, mode="edit")
def _edit_datetime(value, spec, field):
    from pyvelm.widgets.datetime_pickers import render_datetime_picker

    return render_datetime_picker(value, spec, field, env=_spec_env(spec))


@widget(Time, mode="edit")
def _edit_time(value, spec, field):
    from pyvelm.widgets.datetime_pickers import render_time_picker

    return render_time_picker(value, spec, field)


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


def _render_file_picker_widget(
    value, spec, field, *, multi: bool, readonly: bool
) -> Markup:
    """Edit-mode widget for ``Many2one("ir.attachment") widget="file"``
    (or M2m widget="files"). Renders a chip list of already-picked
    attachments + a button that opens the picker dialog.

    ``widget_options`` accepted on the field spec:
      - ``accept``: mimetype filter passed to the dialog and the file
        input ("image/*", "application/pdf,image/*").
    """
    accept = (
        spec.get("accept")
        or (spec.get("widget_options") or {}).get("accept")
        or ""
    )
    initial: list[dict] = []
    if multi:
        records = value if hasattr(value, "_ids") else None
        if records is not None:
            for rec in records:
                mime = (getattr(rec, "mimetype", "") or "").lower()
                initial.append(
                    {
                        "id": rec.id,
                        "name": getattr(rec, "name", "") or f"#{rec.id}",
                        "mimetype": mime,
                        "thumbnail_url": (
                            f"/api/attachment/{rec.id}/download"
                            if mime.startswith("image/")
                            else ""
                        ),
                    }
                )
    else:
        rec = value if (value and hasattr(value, "_ids") and value._ids) else None
        if rec is not None:
            mime = (getattr(rec, "mimetype", "") or "").lower()
            initial.append(
                {
                    "id": rec.id,
                    "name": getattr(rec, "name", "") or f"#{rec.id}",
                    "mimetype": mime,
                    "thumbnail_url": (
                        f"/api/attachment/{rec.id}/download"
                        if mime.startswith("image/")
                        else ""
                    ),
                }
            )
    partial = _env.get_template("widgets/file_picker_field.html")
    return Markup(
        partial.render(
            name=spec["name"],
            multi=multi,
            readonly=readonly,
            accept=accept,
            initial=initial,
        )
    )


@widget(Many2one, hint="file", mode="edit")
def _edit_file(value, spec, field):
    return _render_file_picker_widget(
        value, spec, field, multi=False, readonly=bool(spec.get("readonly"))
    )


@widget(Many2many, hint="files", mode="edit")
def _edit_files(value, spec, field):
    return _render_file_picker_widget(
        value, spec, field, multi=True, readonly=bool(spec.get("readonly"))
    )


@widget(Many2one, hint="file")
def _display_file(value, spec, field):
    """Display: chip + link to download (or thumbnail for image MIMEs)."""
    if not value or not getattr(value, "_ids", None):
        return Markup("")
    rec = value
    mime = (getattr(rec, "mimetype", "") or "").lower()
    name = escape(getattr(rec, "name", "") or f"#{rec.id}")
    url = f"/api/attachment/{rec.id}/download"
    if mime.startswith("image/"):
        return Markup(
            f'<a href="{url}" target="_blank" '
            f'class="inline-block max-w-[8rem] rounded-md overflow-hidden border border-default">'
            f'<img src="{url}" alt="" loading="lazy" '
            f'class="block w-full h-auto object-cover" '
            f'onerror="this.style.display=\'none\'"></a>'
        )
    return Markup(
        f'<a href="{url}" target="_blank" '
        f'class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-default '
        f'text-xs text-body hover:bg-neutral-secondary transition">'
        f'<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" '
        f'stroke-width="1.8"><path stroke-linecap="round" stroke-linejoin="round" '
        f'd="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/></svg>'
        f'<span class="truncate max-w-[10rem]">{name}</span></a>'
    )


@widget(Many2many, hint="files")
def _display_files(value, spec, field):
    if not value or not getattr(value, "_ids", None):
        return Markup("")
    pieces = []
    for rec in value:
        single_spec = {**spec}
        pieces.append(str(_display_file(rec, single_spec, field)))
    return Markup(
        '<div class="flex flex-wrap items-center gap-1.5">' + "".join(pieces) + "</div>"
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


def _value_for_widget(env, field: Field, value):
    """Normalize ORM / form-playback values before handing to widgets."""
    if isinstance(field, Many2one):
        Model = env[field.comodel_name]
        if value is None or value is False or value == "":
            return Model
        if hasattr(value, "_fields"):
            # Empty recordset is falsy for widgets; never touch `.id`
            # on it — that property calls ensure_one().
            return value if len(value) else Model
        try:
            return Model.browse(int(value))
        except (TypeError, ValueError):
            return Model
    if isinstance(field, Many2many):
        Model = env[field.comodel_name]
        if value is None or value is False or value == "":
            return Model
        if hasattr(value, "_fields"):
            return value if len(value) else Model
        ids: list[int] = []
        if isinstance(value, (list, tuple)):
            for v in value:
                if v in ("", None):
                    continue
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    pass
        else:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                return Model
        return Model.browse(ids) if ids else Model
    return value


@widget(Many2many, mode="edit")
def _edit_m2m(value, spec, field):
    """Many2many editor — inline search (default) or dialog-only mode."""
    return _render_m2m_editor(value, spec, field, dialog_only=False)


@widget(Many2many, hint="dialog", mode="edit")
def _edit_m2m_dialog(value, spec, field):
    return _render_m2m_editor(value, spec, field, dialog_only=True)


def _render_m2m_editor(value, spec, field, *, dialog_only: bool) -> Markup:
    """Chip editor via ``widgets/m2m_input.html`` / ``pvM2m``."""
    from .web import _display_value

    if not dialog_only and _m2m_use_dialog_editor(spec):
        dialog_only = True

    env = spec.get("_env") or (value.env if hasattr(value, "env") else None)
    if env is None:
        return Markup("")
    records = _value_for_widget(env, field, value)
    initial = (
        [{"id": rec.id, "label": _display_value(rec)} for rec in records]
        if records
        else []
    )
    partial = _env.get_template("widgets/m2m_input.html")
    return Markup(
        partial.render(
            name=spec["name"],
            comodel=spec.get("_comodel") or field.comodel_name,
            search_url=spec.get("_search_url")
            or f"/api/m2o/search?model={field.comodel_name}",
            form_view_url=spec.get("_form_view_url"),
            initial=initial,
            readonly=bool(spec.get("readonly")),
            dialog_only=dialog_only,
        )
    )


@widget(One2many, mode="edit")
def _edit_o2m_field(value, spec, field):
    """Edit-mode O2m: inline table (``widget=\"inline\"``) or dialog table."""
    if _o2m_use_inline_edit(spec):
        return _edit_o2m_table(value, spec, field)
    if _o2m_show_table(spec):
        return _render_o2m_table(value, spec, field)
    return _render_collection(value, spec, field)


# ---- image widget (Char-backed; URL OR upload) ----


def _render_image_widget(value, spec, readonly: bool) -> Markup:
    """Render the image widget bound to a Char value.

    The stored column is just a URL string — either external
    (``https://…``) or a local download URL produced by
    ``/api/attachment/upload``. The widget glues a file picker + URL
    input to the same hidden input; the Alpine component is in
    ``layouts/main.html``.
    """
    partial = _env.get_template("widgets/image.html")
    return Markup(
        partial.render(
            name=spec["name"],
            value=value or "",
            value_json=json.dumps(value or ""),
            readonly=readonly,
        )
    )


@widget(Char, hint="image")
@widget(Text, hint="image")
def _display_image(value, spec, field):
    return _render_image_widget(value, spec, readonly=True)


@widget(Char, hint="image", mode="edit")
@widget(Text, hint="image", mode="edit")
def _edit_image(value, spec, field):
    return _render_image_widget(value, spec, readonly=bool(spec.get("readonly")))


# ---- file_url widget (Char-backed; pick an image from the file library) ----


def _render_file_url_widget(value, spec, *, readonly: bool) -> Markup:
    """Char widget that stores an image URL picked from the file library.

    Bridges the ``file_manager`` library and plain URL columns (company
    logo / favicon, etc.): the operator clicks **Pick from library**,
    chooses an image in the standard ``/web/files/picker`` dialog, and
    the widget stores that attachment's public download URL into the
    Char. A manual URL field stays available for external links.

    ``accept`` (widget option, default ``image/*``) filters the picker.
    """
    accept = (
        spec.get("accept")
        or (spec.get("widget_options") or {}).get("accept")
        or "image/*"
    )
    partial = _env.get_template("widgets/file_url.html")
    return Markup(
        partial.render(
            name=spec["name"],
            value=value or "",
            accept=accept,
            readonly=readonly,
        )
    )


@widget(Char, hint="file_url")
@widget(Text, hint="file_url")
def _display_file_url(value, spec, field):
    return _render_file_url_widget(value, spec, readonly=True)


@widget(Char, hint="file_url", mode="edit")
@widget(Text, hint="file_url", mode="edit")
def _edit_file_url(value, spec, field):
    return _render_file_url_widget(
        value, spec, readonly=bool(spec.get("readonly"))
    )


# ---- color widget (Char-backed hex for company themes) ----


def _render_color_widget(value, spec, readonly: bool) -> Markup:
    partial = _env.get_template("widgets/color.html")
    raw = "" if value is None else str(value).strip()
    return Markup(
        partial.render(
            name=spec["name"],
            value=raw,
            value_json=json.dumps(raw),
            readonly=readonly,
        )
    )


@widget(Char, hint="color")
@widget(Text, hint="color")
def _display_color(value, spec, field):
    return _render_color_widget(value, spec, readonly=True)


@widget(Char, hint="color", mode="edit")
@widget(Text, hint="color", mode="edit")
def _edit_color(value, spec, field):
    return _render_color_widget(value, spec, readonly=bool(spec.get("readonly")))


# ---- attachment widget (field-less; addressed by res_model + res_id) ----


def _attachment_initial(env, res_model: str, res_id: int | None) -> list[dict]:
    """Read the existing ir.attachment rows for ``(res_model, res_id)``.

    Returns one ``{id, name, mimetype, size}`` dict per row, ordered by
    id ascending (= upload order). Yields an empty list when the row's
    res_id isn't set yet (i.e. on a brand-new, unsaved parent record)
    or when ir.attachment isn't loaded at all."""
    if "ir.attachment" not in env.registry or not res_id:
        return []
    rows = env["ir.attachment"].search(
        [("res_model", "=", res_model), ("res_id", "=", res_id)],
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "mimetype": r.mimetype,
            "size": r.file_size or 0,
        }
        for r in rows
    ]


def _render_attachment_widget(
    spec: dict, record, env, model_cls, mode: str
) -> Markup:
    """Render the attachment uploader for a host record.

    Works in both display and edit modes — display just sets
    ``readonly=true`` on the Alpine config which hides the upload
    affordance and the delete buttons."""
    res_model = model_cls._name
    res_id = record.id if record else 0
    initial = _attachment_initial(env, res_model, res_id)
    readonly = (mode == "display") or bool(spec.get("readonly"))
    partial = _env.get_template("widgets/attachment.html")
    return Markup(
        partial.render(
            name=spec.get("name") or "attachment_ids",
            res_model=res_model,
            res_id=res_id,
            initial=initial,
            readonly=readonly,
        )
    )


# ----- Jinja environment -----

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("pyvelm", "templates"),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

from pyvelm.file_size import human_size as _human_size
from pyvelm.icons import register_jinja_globals as _register_icon_globals


def register_shell_globals(jinja_env) -> None:
    """Register shared Jinja globals for framework and module template envs."""
    from pyvelm.branding import default_brand_globals

    _register_icon_globals(jinja_env)
    for key, val in default_brand_globals().items():
        jinja_env.globals.setdefault(key, val)
    jinja_env.filters.setdefault("human_size", _human_size)


register_shell_globals(_env)


def merge_template_context(
    env, current_path: str | None = None, **extra
) -> dict:
    """Merge layout shell + company theme for any Jinja template render."""
    ctx = layout_context(env, current_path) if env is not None else {}
    if env is not None:
        ctx.update(extra)
        return ctx
    from pyvelm.branding import branding_context

    ctx = branding_context(None)
    ctx.update(extra)
    return ctx


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
            form_lookup = _form_view_for_model(env, field.comodel_name)
            spec_copy["_form_view_url"] = (
                f"/web/views/{form_lookup[0]}/{form_lookup[1]}"
                if form_lookup
                else None
            )
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
        if field is not None and field.readonly and "readonly" not in spec_copy:
            spec_copy["readonly"] = True
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
        # currency_field) or env (Datetime → active tz) read these
        # via private keys. Kept off the public spec contract so view
        # authors can't depend on them.
        ro = spec_readonly(spec, field)
        spec_with_rec = {**spec, "_record": record, "_env": record.env, "readonly": ro}
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
        spec_with_env = {**spec, "_env": env}
        cells.append({"name": fname, "html": renderer(value, spec_with_env, field)})
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


def _field_spec_name(spec) -> str:
    return spec if isinstance(spec, str) else spec["name"]


def _filter_fields_spec(fields_spec, column_names: list[str] | None) -> list:
    """Return a subset of field specs in ``column_names`` order."""
    if not column_names:
        return list(fields_spec)
    by_name = {_field_spec_name(s): s for s in fields_spec}
    out = []
    for name in column_names:
        if name in by_name:
            out.append(by_name[name])
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
                "visible_default": spec.get("visible", True) is not False,
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
    return template.render(
        view=view,
        row={"id": record.id, "cells": cells},
        access=template_access(env, view.model),
    )


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


_O2M_NESTED_KEY = re.compile(
    r"^([a-zA-Z_][\w]*)\[(\d+)\]\[([a-zA-Z_][\w]*)\](?:_(date|time))?$"
)


class _O2mRowView:
    """Lightweight row for re-rendering inline-O2m after a failed save.

    Holds the user's submitted cell values so validation errors don't
    wipe what they typed. Many2one cells are browsed on access."""

    __slots__ = ("id", "_env", "_co_name", "_vals")

    def __init__(
        self,
        env,
        co_name: str,
        *,
        id: int | None = None,
        vals: dict | None = None,
    ):
        self._env = env
        self._co_name = co_name
        self.id = id
        self._vals = vals or {}

    def __getattr__(self, name: str):
        if name in self._vals:
            return self._vals[name]
        if self.id is not None:
            return getattr(self._env[self._co_name].browse(self.id), name)
        raise AttributeError(name)


def _o2m_bucket_form(
    form_data, oname: str, co_cls
) -> dict[int, dict[str, Any]]:
    """Group flat form keys ``oname[idx][sub]`` into ``{idx: {sub: val}}``.

    Many2many sub-fields use ``getlist`` so every chip id is kept."""
    by_idx: dict[int, dict[str, Any]] = {}
    keys = list(form_data.keys()) if hasattr(form_data, "keys") else list(form_data)
    for key in keys:
        m = _O2M_NESTED_KEY.match(key)
        if not m or m.group(1) != oname:
            continue
        idx = int(m.group(2))
        sub = m.group(3)
        part = m.group(4)
        sub_field = co_cls._fields.get(sub)
        bucket = by_idx.setdefault(idx, {})
        if isinstance(sub_field, Datetime) and part in ("date", "time"):
            bucket[f"{sub}_{part}"] = form_data[key]
            continue
        if isinstance(sub_field, Many2many):
            posted = (
                form_data.getlist(key)
                if hasattr(form_data, "getlist")
                else [form_data[key]]
            )
            bucket[sub] = [v for v in posted if v not in ("", None)]
        else:
            bucket[sub] = form_data[key]
    return by_idx


def _o2m_row_view_from_raw(env, co_cls, raw: dict) -> _O2mRowView:
    """Turn one indexed form bucket into an :class:`_O2mRowView`."""
    raw = dict(raw)
    op = raw.pop("_op", "update")
    rid_raw = raw.pop("id", None)
    rid: int | None = None
    if op != "create" and rid_raw not in (None, ""):
        try:
            rid = int(rid_raw)
        except (TypeError, ValueError):
            rid = None
    vals: dict = {}
    for sub_name, sub_raw in raw.items():
        sub_field = co_cls._fields.get(sub_name)
        if sub_field is None:
            continue
        if isinstance(sub_field, Many2one):
            if sub_raw in ("", None):
                vals[sub_name] = env[sub_field.comodel_name]
            else:
                try:
                    vals[sub_name] = env[sub_field.comodel_name].browse(int(sub_raw))
                except (TypeError, ValueError):
                    vals[sub_name] = env[sub_field.comodel_name]
        elif isinstance(sub_field, Boolean):
            vals[sub_name] = sub_raw in ("on", "true", "1", True)
        elif isinstance(sub_field, Integer):
            try:
                vals[sub_name] = int(sub_raw) if sub_raw not in ("", None) else None
            except (TypeError, ValueError):
                vals[sub_name] = sub_raw
        elif isinstance(sub_field, Float):
            try:
                vals[sub_name] = float(sub_raw) if sub_raw not in ("", None) else None
            except (TypeError, ValueError):
                vals[sub_name] = sub_raw
        elif isinstance(sub_field, Many2many):
            ids: list[int] = []
            raw_list = sub_raw if isinstance(sub_raw, list) else [sub_raw]
            for v in raw_list:
                if v in ("", None):
                    continue
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    pass
            vals[sub_name] = (
                env[sub_field.comodel_name].browse(ids)
                if ids
                else env[sub_field.comodel_name]
            )
        else:
            vals[sub_name] = sub_raw if sub_raw not in ("",) else None
    return _O2mRowView(env, co_cls._name, id=rid if op != "create" else None, vals=vals)


def _o2m_playback_rows(form_data, oname: str, co_cls, env) -> list[tuple[int, _O2mRowView, str]]:
    """Rebuild inline-O2m rows from posted form data (failed-save playback).

    Returns ``(form_index, row_view, op)`` tuples sorted by index.
    Rows marked ``delete`` are included so the UI can strike them out."""
    out: list[tuple[int, _O2mRowView, str]] = []
    for idx, raw in sorted(_o2m_bucket_form(form_data, oname, co_cls).items()):
        op = raw.get("_op", "update")
        out.append((idx, _o2m_row_view_from_raw(env, co_cls, raw), op))
    return out


def _parse_scalar(field, raw, env=None):
    """Coerce a form-submitted string to its field's Python type.

    Returns (value, error_msg | None). Caller decides whether to
    apply the value or stash the error against the field name.

    ``env`` is consulted for Datetime fields to reverse the tz shift
    applied by ``_edit_datetime`` (user types local, we store UTC).
    Pass ``env=None`` to keep the legacy "naive = UTC" interpretation.
    """
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
            dt = field.to_sql_param(raw)
            return (_localize_datetime_for_storage(dt, env), None)
        if isinstance(field, Date):
            return (field.to_sql_param(raw), None)
        if isinstance(field, Time):
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
        if isinstance(field, Time):
            return (None, "Must be a time (HH:MM).")
        return (None, "Invalid value.")


def _localize_datetime_for_storage(dt, env):
    """Shift user-local naive datetimes to naive UTC for storage."""
    if dt is not None and env is not None and dt.tzinfo is None:
        tz = _active_tz(env)
        if tz is not _UTC:
            return dt.replace(tzinfo=tz).astimezone(_UTC).replace(tzinfo=None)
    return dt


def _parse_datetime_field(
    form_data, fname: str, field: Datetime, *, env
) -> tuple[Any, str | None]:
    """Parse a Datetime from one ``datetime-local`` value or legacy split fields."""
    from pyvelm.widgets.datetime_pickers import combine_datetime_form_values

    combined, err = combine_datetime_form_values(form_data, fname, env=env)
    if err:
        return None, err
    if combined is None:
        if getattr(field, "required", False):
            return None, "This field is required."
        return None, None
    try:
        dt = field.to_sql_param(combined)
        return (_localize_datetime_for_storage(dt, env), None)
    except (TypeError, ValueError):
        return None, "Must be a datetime."


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
    o2m_names: set[str] = set()
    for key in keys:
        m = _O2M_NESTED_KEY.match(key)
        if not m:
            continue
        oname = m.group(1)
        if isinstance(model_cls._fields.get(oname), One2many):
            o2m_names.add(oname)
    for oname in o2m_names:
        ofield = model_cls._fields[oname]
        co_cls = env.registry[ofield.comodel_name]
        by_field[oname] = _o2m_bucket_form(form_data, oname, co_cls)

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
            for sub_name in list(raw.keys()):
                if sub_name.endswith("_date") or sub_name.endswith("_time"):
                    base = sub_name.rsplit("_", 1)[0]
                    if isinstance(co_cls._fields.get(base), Datetime):
                        continue
                sub_raw = raw[sub_name]
                sub_field = co_cls._fields.get(sub_name)
                if sub_field is None or not sub_field.is_stored:
                    continue
                if isinstance(sub_field, Datetime) and (
                    f"{sub_name}_date" in raw or f"{sub_name}_time" in raw
                ):
                    mini = {
                        f"{sub_name}_date": raw.get(f"{sub_name}_date", ""),
                        f"{sub_name}_time": raw.get(f"{sub_name}_time", ""),
                    }
                    value, err = _parse_datetime_field(
                        mini, sub_name, sub_field, env=env
                    )
                else:
                    value, err = _parse_scalar(sub_field, sub_raw, env)
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


def parse_form_vals(model_cls, form_data, env=None) -> tuple[dict, dict]:
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
        try:
            from pyvelm.timestamps import is_system_timestamp_field
        except ImportError:
            is_system_timestamp_field = lambda _c, _f: False  # noqa: E731
        if is_system_timestamp_field(model_cls, fname):
            continue
        if isinstance(field, Datetime) and (
            fname in form_data
            or f"{fname}_date" in form_data
            or f"{fname}_time" in form_data
        ):
            parsed, err = _parse_datetime_field(form_data, fname, field, env=env)
            if err:
                errors[fname] = err
            else:
                vals[fname] = parsed
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
            elif isinstance(field, Date):
                vals[fname] = field.to_sql_param(raw)
            elif isinstance(field, Time):
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
            elif isinstance(field, Time):
                errors[fname] = "Must be a time (HH:MM)."
            else:
                errors[fname] = "Invalid value."
    from .vellum.fillable import filter_mass_assignment

    vals = filter_mass_assignment(model_cls, vals)
    return vals, errors


# ---- form view rendering ----


def _resolve_colspan(raw, cols: int) -> int:
    """Clamp ``raw`` to ``[1, cols]``.

    Accepts ``"full"`` (== cols), an int, or ``None`` (== 1). Anything
    unparseable falls back to 1 so a typo in arch can't blow up render.
    """
    if raw is None:
        return 1
    if isinstance(raw, str):
        if raw.lower() == "full":
            return cols
        try:
            raw = int(raw)
        except ValueError:
            return 1
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    return min(n, cols)


def _form_section_html(
    section_spec,
    record_or_none,
    env,
    model_cls,
    mode: str,
    errors: dict | None = None,
    submitted: dict | None = None,
    prefill: dict | None = None,
    form_playback=None,
    cols: int = 2,
) -> list[dict]:
    """Build the per-field HTML for one section.

    Returns a list of cell dicts (``{name, label, required, error, html,
    colspan, wide}``). ``cols`` is the section's column count used to
    clamp each cell's ``colspan`` (``"full"`` becomes ``cols``).

    ``errors`` is the ``{field_name: message}`` map from a previous failed
    save; ``submitted`` is the ``vals`` from that same attempt so the user
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
            # Pure-widget entries (no backing field on the host model).
            # ``widget="attachment"`` is the first of these — generic
            # over (res_model, res_id), so it doesn't need a column.
            if spec.get("widget") == "attachment":
                html = _render_attachment_widget(
                    spec, record_or_none, env, model_cls, mode
                )
                cells.append({
                    "name": fname,
                    "label": spec.get("label") or "Attachments",
                    "required": False,
                    "error": None,
                    "wide": True,
                    "colspan": cols,
                    "html": html,
                })
                continue
            cells.append({
                "name": fname,
                "label": fname,
                "html": Markup(""),
                "colspan": _resolve_colspan(spec.get("colspan"), cols),
                "wide": False,
            })
            continue
        field = model_cls._fields[fname]
        label = spec.get("label") or field.string or fname
        hint = spec.get("widget")
        ro = spec_readonly(spec, field)
        try:
            from pyvelm.timestamps import is_system_timestamp_field
        except ImportError:
            is_system_timestamp_field = lambda _c, _f: False  # noqa: E731
        render_mode = mode
        if mode == "edit" and is_system_timestamp_field(model_cls, fname):
            render_mode = "display"
        renderer = find_renderer(field, hint, mode=render_mode)

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

        spec_with_rec = {
            **spec,
            "_record": record_or_none,
            "_env": env,
            "_o2m_errors": errors,
            "_form_playback": form_playback,
            "readonly": ro,
        }
        # Author-declared colspan wins. As a safety net, anything that
        # embeds a table-like widget (O2m grid, HTML editor) defaults to
        # full-width so the inner UI isn't squashed.
        author_span = spec.get("colspan")
        is_wide_default = (
            isinstance(field, One2many)
            and (_o2m_use_inline_edit(spec) or _o2m_show_table(spec))
        ) or (
            isinstance(field, (Html, Code))
            or (
                isinstance(field, Text)
                and spec.get("widget") in ("html", "code")
            )
        )
        if author_span is None and is_wide_default:
            cell_span = cols
        else:
            cell_span = _resolve_colspan(author_span, cols)
        field_error = errors.get(fname)
        if field_error is None and isinstance(field, One2many):
            prefix = f"{fname}["
            for ek, msg in errors.items():
                if ek.startswith(prefix):
                    field_error = msg
                    break
        cells.append(
            {
                "name": fname,
                "label": label,
                "required": getattr(field, "required", False),
                "readonly": ro,
                "error": field_error,
                "wide": cell_span >= cols,
                "colspan": cell_span,
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
    form_playback=None,
) -> list[dict]:
    from .views import resolve_arch

    arch = resolve_arch(view)
    model_cls = env.registry[view.model]
    sections_spec = arch.get("sections", [])
    form_cols = _resolve_form_cols(arch.get("cols"))
    out: list[dict] = []
    for spec in sections_spec:
        section_cols = _resolve_form_cols(spec.get("cols"), default=form_cols)
        out.append(
            {
                "name": spec.get("name"),
                "title": spec.get("title") or spec.get("name", ""),
                "cols": section_cols,
                "cells": _form_section_html(
                    spec,
                    record_or_none,
                    env,
                    model_cls,
                    mode,
                    errors=errors,
                    submitted=submitted,
                    prefill=prefill,
                    form_playback=form_playback,
                    cols=section_cols,
                ),
            }
        )
    return out


def _resolve_form_cols(raw, default: int = 2) -> int:
    """Clamp a form/section ``cols`` value into the supported range.

    Practical cap is 12 (Bootstrap-style); 1 is the minimum. Anything
    unparseable falls back to ``default`` so a typo in arch doesn't
    crash render.
    """
    if raw is None:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return 1
    return min(n, 12)


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


_RECORD_NAV_CAP = 5000


def parse_bc_param(bc: str | None) -> list[tuple[str, str]]:
    """Parse ``bc=mod/view,mod2/view2`` into an ordered ancestor stack."""
    if not bc or not str(bc).strip():
        return []
    out: list[tuple[str, str]] = []
    for part in str(bc).split(","):
        part = part.strip()
        if "/" not in part:
            continue
        module, name = part.split("/", 1)
        if module and name:
            out.append((module, name))
    return out


def format_bc_param(stack: list[tuple[str, str]]) -> str:
    """Encode a breadcrumb ancestor stack for URL query params."""
    return ",".join(f"{m}/{n}" for m, n in stack)


def encode_view_nav_query(
    ref_module: str | None,
    ref_name: str | None,
    *,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
) -> str:
    """Query string carrying the parent view and nav history onto form URLs.

    * ``ref`` — immediate parent view (``module/viewname``, any view type).
    * ``bc`` — comma-separated ancestor chain (oldest first), Odoo-style.
    * ``list`` — legacy alias of ``ref`` when the parent is a list view.
    """
    params: dict[str, str] = {}
    if ref_module and ref_name:
        ref = f"{ref_module}/{ref_name}"
        params["ref"] = ref
    bc = format_bc_param(bc_stack or [])
    if bc:
        params["bc"] = bc
    if search:
        params["search"] = search
    if order:
        params["order"] = order
    if filters:
        params["filters"] = filters
    if group_by:
        params["group_by"] = group_by
    if page is not None and page > 0:
        params["page"] = str(page)
    if page_size is not None:
        params["page_size"] = str(page_size)
    if ref_module and ref_name:
        # Legacy alias — form nav parser still accepts ``list=``.
        params["list"] = params["ref"]
    return urlencode(params)


def encode_list_nav_query(
    list_module: str | None,
    list_name: str | None,
    *,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
) -> str:
    """Query string carrying list/kanban context onto form URLs."""
    return encode_view_nav_query(
        list_module,
        list_name,
        search=search,
        order=order,
        filters=filters,
        group_by=group_by,
        page=page,
        page_size=page_size,
        bc_stack=bc_stack,
    )


def _list_view_domain_and_order(
    list_view,
    env,
    *,
    search: str = "",
    order: str = "",
    filters: str = "",
) -> tuple[list, str]:
    """Mirror ``render_list_page`` domain + ORDER BY for record navigation."""
    from .views import resolve_arch

    arch = resolve_arch(list_view)
    fields_spec = arch.get("fields", [])
    model_cls = env.registry[list_view.model]

    domain: list = list(arch.get("domain") or [])
    if search:
        domain.extend(_build_search_domain(model_cls, fields_spec, search))
    domain.extend(_parse_filters(model_cls, fields_spec, filters))

    sequence_field = arch.get("sequence")
    if sequence_field and sequence_field in model_cls._fields:
        safe_ord = f'"{sequence_field}" ASC, "id" ASC'
    else:
        safe_ord = _safe_order(fields_spec, order)
    return domain, safe_ord


def _search_ui_views(env, domain: list, **kwargs):
    """Search ``ir.ui.view`` bypassing ACL — UI arch is system metadata.

    Mirrors ``_menu``: every authenticated session needs view definitions
    to render pages. ``ir.model.access`` grants are still seeded for
    shell/admin use; the web layer does not depend on them.
    """
    prev = env._acl_bypass
    env._acl_bypass = True
    try:
        return env["ir.ui.view"].search(domain, **kwargs)
    finally:
        env._acl_bypass = prev


def _load_ui_view(env, module: str | None, name: str | None):
    """Load ``ir.ui.view`` by module + name (any view type)."""
    if not module or not name:
        return None
    matches = _search_ui_views(
        env,
        [("module", "=", module), ("name", "=", name)],
        limit=1,
    )
    if not matches:
        return None
    rec = matches
    rec.ensure_one()
    return rec


def _load_ref_view(
    env,
    ref_module: str | None,
    ref_name: str | None,
    model: str,
):
    """Resolve the parent view for form prev/next; fall back to any list."""
    if ref_module and ref_name:
        rec = _load_ui_view(env, ref_module, ref_name)
        if rec is not None and rec.model == model:
            return rec
    lookup = _list_view_for_model(env, model)
    if not lookup:
        return None
    mod, name = lookup
    return _load_ui_view(env, mod, name)


def _load_list_view(env, list_module: str | None, list_name: str | None, model: str):
    """Resolve a list view for prev/next; fall back to any list on *model*."""
    rec = _load_ref_view(env, list_module, list_name, model)
    if rec is not None and rec.view_type == "list":
        return rec
    lookup = _list_view_for_model(env, model)
    if not lookup:
        return None
    mod, name = lookup
    rec = _load_ui_view(env, mod, name)
    if rec is not None and rec.view_type == "list":
        return rec
    return None


def _ref_view_domain_and_order(
    ref_view,
    env,
    *,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
) -> tuple[list, str]:
    """Domain + ORDER BY for record pager following a list or kanban parent."""
    from .views import resolve_arch

    arch = resolve_arch(ref_view)
    model_cls = env.registry[ref_view.model]

    if ref_view.view_type == "kanban":
        fields_spec = _kanban_fields_spec(ref_view, arch, env)
        domain: list = []
        if search:
            domain.extend(_build_search_domain(model_cls, fields_spec, search))
        domain.extend(_parse_filters(model_cls, fields_spec, filters))
        seq_field = arch.get("sequence")
        if seq_field and seq_field in model_cls._fields:
            safe_ord = f'"{seq_field}" ASC, "id" ASC'
        elif order:
            safe_ord = _safe_order(fields_spec, order)
        else:
            safe_ord = '"id" ASC'
        return domain, safe_ord

    if ref_view.view_type == "list":
        return _list_view_domain_and_order(
            ref_view,
            env,
            search=search,
            order=order,
            filters=filters,
        )

    return [], '"id" ASC'


def _record_pager(
    env,
    *,
    model: str,
    record_id: int,
    form_module: str,
    form_name: str,
    mode: str,
    list_module: str | None = None,
    list_name: str | None = None,
    list_search: str = "",
    list_order: str = "",
    list_filters: str = "",
    group_by: str = "",
    bc_stack: list[tuple[str, str]] | None = None,
) -> dict | None:
    """Prev/next URLs following the parent view's search, filters, and sort."""
    ref_view = _load_ref_view(env, list_module, list_name, model)
    if ref_view is None:
        return None

    domain, safe_ord = _ref_view_domain_and_order(
        ref_view,
        env,
        search=list_search,
        order=list_order,
        filters=list_filters,
        group_by=group_by,
    )
    Model = env[model]
    recs = Model.search(domain, order=safe_ord, limit=_RECORD_NAV_CAP)
    ids = list(recs.ids)
    if record_id not in ids:
        return None

    idx = ids.index(record_id)
    nav_qs = encode_view_nav_query(
        ref_view.module,
        ref_view.name,
        search=list_search,
        order=list_order,
        filters=list_filters,
        group_by=group_by,
        bc_stack=bc_stack,
    )
    suffix = "/edit" if mode == "edit" else ""
    base = f"/web/views/{form_module}/{form_name}/record"

    def _url(rid: int) -> str:
        path = f"{base}/{rid}{suffix}"
        return f"{path}?{nav_qs}" if nav_qs else path

    total = len(ids)
    if total == 1:
        prev_id = next_id = ids[0]
    else:
        prev_id = ids[(idx - 1) % total]
        next_id = ids[(idx + 1) % total]

    return {
        "prev_url": _url(prev_id),
        "next_url": _url(next_id),
        "index": idx + 1,
        "total": total,
        "nav_qs": nav_qs,
    }


def _model_has_mail_thread(env, model_name: str) -> bool:
    """True when *model_name* inherits :class:`~pyvelm.mail.MailThread`."""
    if model_name not in env.registry:
        return False
    from pyvelm.mail import MailThread

    try:
        return issubclass(env.registry[model_name], MailThread)
    except TypeError:
        return False


def _record_title(record_or_none, view_model: str, mode: str) -> str:
    """Best-effort short title for the form header."""
    if mode == "new" or record_or_none is None:
        return f"New {_humanize_model(view_model, plural=False)}"
    cls = type(record_or_none)
    if "display_name" in cls._fields:
        dn = getattr(record_or_none, "display_name", None)
        if dn:
            return str(dn)
    return f"{view_model} #{record_or_none.id}"


def _resolve_header_actions(
    actions,
    env,
    *,
    model: str,
    module: str,
    name: str,
    record_id,
    record=None,
) -> list[dict]:
    """Materialize a form's display-mode header actions.

    Granular gating: an action that declares the ``perm`` it needs is
    *hidden* — not rendered-then-denied — when the user lacks that grant
    (checked against ``model`` by default, or the action's own ``model``
    override). Actions with no ``perm`` stay visible to anyone who can
    read the record. ``{id}`` in the URL is substituted, and any URL
    that leaves the current view is flagged ``full_page``.
    """
    out: list[dict] = []
    for act in actions or []:
        perm = act.get("perm")
        if perm and not env.has_access(act.get("model") or model, perm):
            continue
        policy = act.get("policy")
        if policy:
            # Record-aware gating (Laravel-like policies): hide the action
            # when the policy method denies it.
            rec = record
            if rec is None:
                try:
                    rec = env[model].browse(record_id)
                except Exception:  # noqa: BLE001
                    rec = None
            if rec is None or not env.can(rec, str(policy), perm=perm):
                continue
        url = (act.get("url") or "").replace("{id}", str(record_id))
        out.append(
            {
                "label": act.get("label", "Run"),
                "url": url,
                "method": (act.get("method") or "POST").upper(),
                "confirm": act.get("confirm") or "",
                "full_page": bool(
                    act.get("full_page")
                    or not url.startswith(f"/web/views/{module}/{name}")
                ),
            }
        )
    return out


def render_form_page(
    view,
    record_or_none,
    env,
    *,
    mode: str,
    body_only: bool = False,
    current_path: str | None = None,
    list_module: str | None = None,
    list_name: str | None = None,
    list_search: str = "",
    list_order: str = "",
    list_filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
    errors: dict | None = None,
    submitted: dict | None = None,
    form_error: str | None = None,
    prefill: dict | None = None,
    form_playback=None,
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
        form_playback=form_playback,
    )
    title = _record_title(record_or_none, view.model, mode)
    template_name = "form_body.html" if body_only else "form.html"
    template = _env.get_template(template_name)
    # Title lives in the layout heading only — breadcrumbs stop at the list.
    if body_only:
        ctx = {}
    else:
        from pyvelm.menu import build_menu_tree

        prelim_menu = build_menu_tree(env, current_path)
        form_crumbs = build_form_breadcrumbs(
            prelim_menu,
            env,
            ref_module=list_module,
            ref_name=list_name,
            bc_stack=bc_stack,
            search=list_search,
            order=list_order,
            filters=list_filters,
            group_by=group_by,
            page=page,
            page_size=page_size,
        )
        ctx = layout_context(env, current_path, breadcrumbs=form_crumbs)
        ctx["subtitle"] = f"{view.model} · {mode}"
    # Resolve header actions: substitute {id} with the current record's
    # id (display-mode only; new/edit records can't take row-level
    # actions). Anything without an id falls through with an empty list.
    from .views import resolve_arch

    arch = resolve_arch(view)
    header_actions: list[dict] = []
    if mode == "display" and record_or_none is not None and record_or_none._ids:
        header_actions = _resolve_header_actions(
            arch.get("header_actions", []),
            env,
            model=view.model,
            module=view.module,
            name=view.name,
            record_id=record_or_none.id,
            record=record_or_none,
        )
    workflow_ctx = None
    if (
        mode == "display"
        and record_or_none is not None
        and record_or_none._ids
        and "workflow.instance" in env.registry
    ):
        from pyvelm.workflow.service import form_context as workflow_form_context

        workflow_ctx = workflow_form_context(env, view.model, record_or_none.id)

    chatter_ctx = None
    if (
        mode == "display"
        and record_or_none is not None
        and record_or_none._ids
    ):
        from pyvelm.mail_chatter import form_chatter_context

        chatter_ctx = form_chatter_context(
            env,
            view.model,
            record_or_none.id,
            enabled=_model_has_mail_thread(env, view.model),
        )

    record_pager = None
    if mode in ("display", "edit") and record_or_none is not None and record_or_none._ids:
        record_pager = _record_pager(
            env,
            model=view.model,
            record_id=record_or_none.id,
            form_module=view.module,
            form_name=view.name,
            mode=mode,
            list_module=list_module,
            list_name=list_name,
            list_search=list_search,
            list_order=list_order,
            list_filters=list_filters,
            group_by=group_by,
            bc_stack=bc_stack,
        )
    return template.render(
        view=view,
        record=record_or_none,
        record_id=(record_or_none.id if record_or_none else None),
        title=title,
        mode=mode,
        body_only=body_only,
        sections=sections,
        form_error=form_error,
        header_actions=header_actions,
        workflow_context=workflow_ctx,
        chatter_context=chatter_ctx,
        record_pager=record_pager,
        list_nav_query=encode_view_nav_query(
            list_module,
            list_name,
            search=list_search,
            order=list_order,
            filters=list_filters,
            group_by=group_by,
            page=page,
            page_size=page_size,
            bc_stack=bc_stack,
        ),
        access=template_access(env, view.model),
        **ctx,
    )


def render_chatter_panel(
    env,
    res_model: str,
    res_id: int,
    *,
    filter_key: str = "all",
    composer_mode: str = "note",
    error: str | None = None,
) -> str:
    """HTMX fragment: chatter log + composer for one record."""
    from pyvelm.mail_chatter import form_chatter_context

    ctx = form_chatter_context(
        env,
        res_model,
        res_id,
        enabled=_model_has_mail_thread(env, res_model),
        filter_key=filter_key,
        composer_mode=composer_mode,
    )
    if ctx is None:
        return ""
    if error:
        ctx = {**ctx, "error": error}
    return _env.get_template("_chatter_panel.html").render(chatter_context=ctx)


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


def _kanban_group_field_kind(model_cls, group_field: str) -> str:
    """Return ``m2o``, ``boolean``, or ``scalar`` for a kanban column key."""
    from .fields import Boolean, Many2one

    field = model_cls._fields.get(group_field)
    if isinstance(field, Many2one):
        return "m2o"
    if isinstance(field, Boolean):
        return "boolean"
    return "scalar"


def _kanban_sort_records(records, arch: dict, model_cls) -> list:
    """Order records by arch ``sequence`` when declared on the model."""
    seq = arch.get("sequence")
    if seq and seq in model_cls._fields:
        return sorted(
            records,
            key=lambda r: (getattr(r, seq, None) or 0, r.id),
        )
    return list(records)


def _kanban_resolve_group_field(view, arch, payload_group_by: str) -> str | None:
    """Return the active grouping field for drag-drop (arch or URL)."""
    arch_group = arch.get("group_by")
    if arch_group:
        if payload_group_by and payload_group_by != arch_group:
            raise ValueError(
                f"group_by {payload_group_by!r} does not match arch {arch_group!r}"
            )
        return arch_group
    return payload_group_by or None


def _kanban_group_write_value(model_cls, group_field: str, column_key) -> object:
    """Map a JSON column key to a value suitable for ``write()``."""
    from .fields import Boolean, Many2one

    field = model_cls._fields[group_field]
    if isinstance(field, Many2one):
        return column_key if column_key else False
    if isinstance(field, Boolean):
        return bool(column_key)
    return column_key


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


def _kanban_fields_spec_from_card(arch: dict) -> list:
    """Build minimal field specs from kanban card layout."""
    card = arch.get("card") or {}
    names: list[str] = []
    for attr in ("title", "subtitle"):
        v = card.get(attr)
        if v and isinstance(v, str) and v not in names:
            names.append(v)
    for spec in (card.get("fields") or []) + (card.get("badges") or []):
        n = _field_spec_name(spec)
        if n not in names:
            names.append(n)
    return [{"name": n} for n in names]


def _kanban_fields_spec(view, arch, env) -> list:
    """Field specs for kanban search/filter/group — prefer a sibling list view."""
    if "ir.ui.view" not in env.registry:
        return _kanban_fields_spec_from_card(arch)
    from .views import resolve_arch

    for domain in (
        [("module", "=", view.module), ("model", "=", view.model), ("view_type", "=", "list")],
        [("model", "=", view.model), ("view_type", "=", "list")],
    ):
        matches = _search_ui_views(
            env,
            domain,
            limit=1,
            order='"priority" ASC, "id" ASC',
        )
        if matches:
            matches.ensure_one()
            list_arch = resolve_arch(matches)
            fields = list_arch.get("fields")
            if fields:
                return list(fields)
    return _kanban_fields_spec_from_card(arch)


def _kanban_card_kw(view, arch, form_view: str | None) -> dict:
    card = arch.get("card", {})
    return dict(
        title_attr=card.get("title"),
        subtitle_attr=card.get("subtitle"),
        image_attr=card.get("image"),
        fields_spec=list(card.get("fields", [])),
        badges_spec=list(card.get("badges", [])),
        form_view=form_view,
        view=view,
    )


def _kanban_build_layout(
    recs,
    *,
    grouped: bool,
    group_field: str | None,
    card_kw: dict,
    arch: dict,
    env,
) -> tuple[list[dict], list[dict]]:
    columns: list[dict] = []
    flat_cards: list[dict] = []
    if grouped and group_field:
        model_cls = env.registry[recs._name]
        for grp in _group_records(recs, group_field, env):
            ordered = _kanban_sort_records(grp["records"], arch, model_cls)
            cards = _kanban_cards_for_records(ordered, **card_kw)
            columns.append(
                {
                    "label": grp["label"],
                    "key": grp["key"],
                    "count": len(ordered),
                    "cards": cards,
                }
            )
    else:
        flat_cards = _kanban_cards_for_records(recs, **card_kw)
    return columns, flat_cards


def _kanban_fetch(
    view,
    arch,
    env,
    *,
    page: int,
    page_size: int,
    search: str,
    order: str,
    filters: str,
    url_group_by: str,
    extra_domain: list | None = None,
) -> dict:
    """Resolve domain, grouping, and record slice for a kanban view.

    ``extra_domain`` lets callers inject a base filter (e.g. the
    file_manager Library page applies ``[("folder_id","=",X)]``)
    without forking the renderer or building a new view per filter.
    """
    arch_group_by = arch.get("group_by")
    list_controls = not arch_group_by
    model_cls = env.registry[view.model]
    Model = env[view.model]
    form_view = arch.get("form_view")

    seq_field = arch.get("sequence")
    if seq_field and seq_field not in model_cls._fields:
        seq_field = None

    if not list_controls:
        order = (
            f'"{seq_field}" ASC, "id" ASC'
            if seq_field
            else '"id" ASC'
        )
        recs = Model.search(list(extra_domain or []), order=order)
        return {
            "list_controls": False,
            "grouped": True,
            "group_field": arch_group_by,
            "recs": recs,
            "total": len(recs),
            "total_pages": 1,
            "page": 0,
            "page_size": page_size,
            "headers": [],
            "search": "",
            "order": "",
            "filters": "",
            "group_by": "",
            "form_view": form_view,
            "sequence_field": seq_field,
        }

    fields_spec = _kanban_fields_spec(view, arch, env)
    headers = _field_headers(model_cls, fields_spec)
    domain: list = list(extra_domain or [])
    if search:
        domain.extend(_build_search_domain(model_cls, fields_spec, search))
    domain.extend(_parse_filters(model_cls, fields_spec, filters))
    safe_group_by = (
        url_group_by
        if any(
            h["name"] == url_group_by and h["group_kind"] != "none" for h in headers
        )
        else ""
    )
    group_field = safe_group_by or None
    grouped = bool(group_field)
    safe_ord = _safe_order(fields_spec, order)
    total = Model.search_count(domain)

    if grouped:
        _GROUP_CAP = 500
        if seq_field:
            safe_ord = f'"{seq_field}" ASC, "id" ASC'
        recs = Model.search(domain, limit=_GROUP_CAP, order=safe_ord)
        total_pages = 1
        page = 0
    else:
        offset = page * page_size
        recs = Model.search(domain, limit=page_size, offset=offset, order=safe_ord)
        total_pages = max(1, (total + page_size - 1) // page_size)

    return {
        "list_controls": True,
        "grouped": grouped,
        "group_field": group_field,
        "recs": recs,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "headers": headers,
        "search": search,
        "order": order,
        "filters": filters,
        "group_by": safe_group_by,
        "form_view": form_view,
        "sequence_field": seq_field,
    }


def _kanban_subtitle(*, total: int, grouped: bool, columns_count: int) -> str:
    """Kanban heading subtitle. Returns an empty string by design — the
    record count is already visible on the pager footer (table mode) or
    via column tallies / card layout (kanban mode), so duplicating it
    under the page title is noise. Kept as a function so callers stay
    decoupled from the rendering decision."""
    return ""


def _kanban_cards_for_records(
    records,
    *,
    title_attr,
    subtitle_attr,
    fields_spec,
    badges_spec,
    form_view,
    view,
    image_attr: str | None = None,
    nav_query: str = "",
) -> list[dict]:
    """Build card dicts for kanban template rendering."""
    cards = []
    for rec in records:
        link = None
        if form_view:
            link = f"/web/views/{view.module}/{form_view}/record/{rec.id}"
            if nav_query:
                link = f"{link}?{nav_query}"
        image_url = ""
        if image_attr:
            raw = getattr(rec, image_attr, None)
            if raw:
                image_url = str(raw).strip()
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
                "image_url": image_url,
                "fields": [_render_field_label(rec, s) for s in fields_spec],
                "badges": [_render_field_label(rec, s) for s in badges_spec],
                "link": link,
            }
        )
    return cards


def _render_kanban_content(
    view,
    arch,
    env,
    *,
    page: int,
    page_size: int,
    search: str,
    order: str,
    filters: str,
    url_group_by: str,
    bc_stack: list[tuple[str, str]] | None = None,
    extra_domain: list | None = None,
) -> dict:
    """Shared kanban fetch + card layout for full page and HTMX fragments.

    ``extra_domain`` lets callers (file_manager Library page is the
    first) inject a base filter that survives alongside the user's
    search / column filters.
    """
    state = _kanban_fetch(
        view,
        arch,
        env,
        page=page,
        page_size=page_size,
        search=search,
        order=order,
        filters=filters,
        url_group_by=url_group_by,
        extra_domain=extra_domain,
    )
    card_kw = _kanban_card_kw(view, arch, state["form_view"])
    nav_query = encode_view_nav_query(
        view.module,
        view.name,
        search=search,
        order=order,
        filters=filters,
        group_by=state.get("group_by") or url_group_by,
        page=page,
        page_size=page_size,
        bc_stack=bc_stack,
    )
    card_kw["nav_query"] = nav_query
    group_field = state["group_field"] or arch.get("group_by")
    model_cls = env.registry[view.model]
    columns, flat_cards = _kanban_build_layout(
        state["recs"],
        grouped=state["grouped"],
        group_field=group_field,
        card_kw=card_kw,
        arch=arch,
        env=env,
    )
    page_title = _view_title(view, arch)
    sequence_field = state.get("sequence_field") or arch.get("sequence")
    if sequence_field and sequence_field not in model_cls._fields:
        sequence_field = None
    kanban_draggable = bool(state["grouped"] and group_field)
    return {
        "view": view,
        "grouped": state["grouped"],
        "list_controls": state["list_controls"],
        "columns": columns,
        "cards": flat_cards,
        "total": state["total"],
        "page": state["page"],
        "page_size": state["page_size"],
        "total_pages": state["total_pages"],
        "search": state["search"],
        "order": state["order"],
        "filters": state["filters"],
        "group_by": state["group_by"],
        "headers": state["headers"],
        "group_field": group_field,
        "group_field_kind": (
            _kanban_group_field_kind(model_cls, group_field)
            if group_field
            else None
        ),
        "sequence_field": sequence_field,
        "kanban_draggable": kanban_draggable,
        "form_view_name": state["form_view"],
        "access": template_access(env, view.model),
        "page_title": page_title,
        "subtitle": _kanban_subtitle(
            total=state["total"],
            grouped=state["grouped"],
            columns_count=len(columns),
        ),
    }


def render_kanban_page(
    view,
    env,
    *,
    page: int = 0,
    page_size: int = 10,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    bc_stack: list[tuple[str, str]] | None = None,
    current_path: str | None = None,
) -> str:
    """Render a kanban view: cards optionally grouped into columns.

    When the arch omits ``group_by``, the board uses the same search,
    filter, URL group-by, and pagination controls as a list view. A
    fixed arch ``group_by`` keeps the classic column board (all records).
    """
    from .views import resolve_arch

    arch = resolve_arch(view)
    ctx = _render_kanban_content(
        view,
        arch,
        env,
        page=page,
        page_size=page_size,
        search=search,
        order=order,
        filters=filters,
        url_group_by=group_by,
        bc_stack=bc_stack,
    )
    template = _env.get_template("kanban.html")
    return template.render(
        **ctx,
        view_switcher=_other_views_for_model(
            env,
            view,
            bc_stack=bc_stack,
            search=search,
            order=order,
            filters=filters,
            group_by=group_by,
            page=page,
            page_size=page_size,
        ),
        bc_param=format_bc_param(bc_stack or []),
        **layout_context(env, current_path, leaf_label=ctx["page_title"]),
    )


def render_kanban_rows(
    view,
    env,
    *,
    page: int = 0,
    page_size: int = 10,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    bc_stack: list[tuple[str, str]] | None = None,
) -> str:
    """Kanban card grid / columns fragment for HTMX toolbar swaps."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    ctx = _render_kanban_content(
        view,
        arch,
        env,
        page=page,
        page_size=page_size,
        search=search,
        order=order,
        filters=filters,
        url_group_by=group_by,
        bc_stack=bc_stack,
    )
    template = _env.get_template("kanban_cards.html")
    return template.render(**ctx)


def _other_views_for_model(
    env,
    view,
    *,
    bc_stack: list[tuple[str, str]] | None = None,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
) -> list[dict]:
    """List sibling views of the same module+model for the view-switcher.

    Returns one entry per sibling (and the current view) shaped as
    ``{label, view_type, href, active}`` ordered list → kanban →
    graph → pivot → form. Form views don't get an entry because
    their URL needs a record id (the bare URL is 501).
    """
    if "ir.ui.view" not in env.registry:
        return []
    # Pull every view registered for the same (module, model). The
    # switcher only shows view types that have a meaningful top-level
    # page — form is bare-URL-only so it gets dropped.
    sibling_types = ("list", "kanban", "graph", "pivot")
    matches = _search_ui_views(
        env,
        [
            ("module", "=", view.module),
            ("model", "=", view.model),
            ("view_type", "in", list(sibling_types)),
        ],
        order='"view_type" ASC, "priority" ASC, "id" ASC',
    )
    # Deduplicate by view_type — first hit (lowest priority) wins,
    # matching the same precedence the loader uses for base views.
    by_type: dict[str, str] = {}
    for m in matches:
        by_type.setdefault(m.view_type, m.name)
    order_priority = {t: i for i, t in enumerate(sibling_types)}
    pairs = sorted(by_type.items(), key=lambda p: order_priority.get(p[0], 99))
    out: list[dict] = []
    for view_type, name in pairs:
        label = {
            "list": "List", "kanban": "Kanban",
            "graph": "Graph", "pivot": "Pivot",
        }.get(view_type, view_type.title())
        active = view.view_type == view_type
        href = f"/web/views/{view.module}/{name}"
        if not active:
            new_bc = list(bc_stack or [])
            new_bc.append((view.module, view.name))
            qs = encode_view_nav_query(
                None,
                None,
                search=search,
                order=order,
                filters=filters,
                group_by=group_by,
                page=page,
                page_size=page_size,
                bc_stack=new_bc,
            )
            if qs:
                href = f"{href}?{qs}"
        elif bc_stack or search or order or filters or group_by:
            qs = encode_view_nav_query(
                None,
                None,
                search=search,
                order=order,
                filters=filters,
                group_by=group_by,
                page=page,
                page_size=page_size,
                bc_stack=bc_stack,
            )
            if qs:
                href = f"{href}?{qs}"
        out.append({
            "label": label,
            "view_type": view_type,
            "href": href,
            "active": active,
        })
    return out


def _format_group_label(value, fname: str, trunc: str | None, model_cls) -> str:
    """Best-effort human label for a read_group raw value.

    The value is whatever ``read_group`` puts in the row dict for a
    given group spec. Many2one labels are pre-resolved by ``read_group``
    and consumed via the ``<spec>__label`` sibling key (which the caller
    reads in preference to this helper) — this function handles the
    *other* primitive cases the renderer might see.
    """
    if value is None:
        return "(no value)"
    if trunc:
        # date_trunc returns a datetime — render a compact label per
        # trunc granularity.
        from datetime import date as _date, datetime as _datetime
        if not isinstance(value, (_date, _datetime)):
            return str(value)
        if trunc == "day":
            return value.strftime("%Y-%m-%d")
        if trunc == "week":
            return value.strftime("Wk %V %Y")
        if trunc == "month":
            return value.strftime("%b %Y")
        if trunc == "quarter":
            quarter = ((value.month - 1) // 3) + 1
            return f"Q{quarter} {value.year}"
        if trunc == "year":
            return str(value.year)
    field = model_cls._fields.get(fname)
    if field is not None and field.__class__.__name__ == "Boolean":
        return "Yes" if value else "No"
    return str(value)


def _parse_view_ref(ref, default_module: str) -> tuple[str, str]:
    """Resolve ``view`` / ``("module", "name")`` widget references."""
    if isinstance(ref, (list, tuple)) and len(ref) >= 2:
        return str(ref[0]), str(ref[1])
    if not isinstance(ref, str):
        raise ValueError(f"view ref must be str or (module, name), got {ref!r}")
    if "/" in ref:
        mod, name = ref.split("/", 1)
        return mod, name
    return default_module, ref


def _find_ui_view(env, module: str, name: str, view_type: str | None = None):
    if "ir.ui.view" not in env.registry:
        return None
    domain = [("module", "=", module), ("name", "=", name)]
    if view_type:
        domain.append(("view_type", "=", view_type))
    recs = _search_ui_views(env, domain, limit=1)
    return recs if recs else None


def _graph_chart_data(
    env,
    *,
    model: str,
    groupby: str,
    measure: str = "__count",
    chart: str = "bar",
    domain: list | None = None,
    search: str = "",
    filters: str = "",
    stacked: bool = False,
    horizontal: bool = False,
) -> dict:
    """Aggregate one measure by one groupby field for chart rendering."""
    model_cls = env.registry[model]
    Model = env[model]
    groupby_spec = groupby
    measure_spec = measure or "__count"
    chart_type = chart or "bar"
    static_domain = list(domain or [])

    pseudo_fields_spec = [
        {"name": n} for n, f in model_cls._fields.items() if f.is_stored
    ]
    full_domain = list(static_domain)
    if search:
        full_domain.extend(_build_search_domain(model_cls, pseudo_fields_spec, search))
    if filters:
        full_domain.extend(_parse_filters(model_cls, pseudo_fields_spec, filters))

    rows = Model.read_group(
        full_domain,
        groupby=[groupby_spec],
        measures=[measure_spec],
    )

    if ":" in groupby_spec:
        gfname, gtrunc = groupby_spec.split(":", 1)
    else:
        gfname, gtrunc = groupby_spec, None
    label_key = f"{groupby_spec}__label"

    labels: list[str] = []
    values: list[float] = []
    for r in rows:
        raw = r.get(groupby_spec)
        if label_key in r and r[label_key] is not None:
            label = str(r[label_key])
        else:
            label = _format_group_label(raw, gfname, gtrunc, model_cls)
        labels.append(label)
        v = r.get(measure_spec, 0)
        try:
            values.append(float(v or 0))
        except (TypeError, ValueError):
            values.append(0.0)

    if measure_spec == "__count":
        measure_label = "Count"
    else:
        mfname = measure_spec.split(":", 1)[0]
        mf = model_cls._fields.get(mfname)
        base_label = (mf.string if mf and mf.string else mfname) if mf else mfname
        agg = measure_spec.split(":", 1)[1] if ":" in measure_spec else "sum"
        measure_label = f"{base_label} ({agg})"

    return {
        "chart_type": chart_type,
        "labels": labels,
        "values": values,
        "measure_label": measure_label,
        "stacked": stacked,
        "horizontal": horizontal,
        "groupby": groupby_spec,
        "measure": measure_spec,
    }


def render_graph_page(
    view,
    env,
    *,
    search: str = "",
    filters: str = "",
    current_path: str | None = None,
) -> str:
    """Render a graph view: one chart aggregating one measure by one
    groupby field, rendered by ApexCharts on the client.

    Arch shape::

        {"groupby": "stage",
         "measure": "expected_revenue:sum",
         "chart":   "bar" | "line" | "pie",
         "title":   "...",      # optional
         "stacked": False,      # optional, bar only
         "horizontal": False,   # optional, bar only
         "domain":  [...]}      # optional, ANDed with URL filters
    """
    from .views import resolve_arch

    arch = resolve_arch(view)
    groupby_spec = arch["groupby"]
    measure_spec = arch.get("measure") or "__count"
    chart_type = arch.get("chart", "bar")
    static_domain = list(arch.get("domain") or [])

    chart_data = _graph_chart_data(
        env,
        model=view.model,
        groupby=groupby_spec,
        measure=measure_spec,
        chart=chart_type,
        domain=static_domain,
        search=search,
        filters=filters,
        stacked=bool(arch.get("stacked")),
        horizontal=bool(arch.get("horizontal")),
    )
    n_groups = len(chart_data["labels"])

    page_title = _view_title(view, arch)

    # Build field lists for toolbar dropdowns.
    from .fields import Boolean, Date, Datetime, Float, Integer, Many2one

    model_cls = env.registry[view.model]
    groupable_fields: list[dict] = []
    measurable_fields: list[dict] = [{"value": "__count", "label": "Count"}]
    for fname, field in model_cls._fields.items():
        if not field.is_stored or field.private:
            continue
        label = field.string or fname
        ft = type(field).__name__
        if isinstance(field, (Many2one, Date, Datetime)):
            groupable_fields.append({"value": fname, "label": label, "type": ft})
            if isinstance(field, (Date, Datetime)):
                for trunc in ("day", "week", "month", "quarter", "year"):
                    groupable_fields.append({
                        "value": f"{fname}:{trunc}",
                        "label": f"{label} ({trunc})",
                        "type": ft,
                    })
        elif not isinstance(field, (Float, Boolean)):
            groupable_fields.append({"value": fname, "label": label, "type": ft})
        if isinstance(field, (Integer, Float)):
            measurable_fields.append({
                "value": f"{fname}:sum",
                "label": f"{label} (sum)",
                "type": ft,
            })
            measurable_fields.append({
                "value": f"{fname}:avg",
                "label": f"{label} (avg)",
                "type": ft,
            })

    template = _env.get_template("graph.html")
    return template.render(
        view=view,
        chart_data=chart_data,
        search=search,
        filters=filters,
        page_title=page_title,
        subtitle=f"{n_groups} group{'s' if n_groups != 1 else ''}",
        view_switcher=_other_views_for_model(env, view),
        groupable_fields=groupable_fields,
        measurable_fields=measurable_fields,
        **layout_context(env, current_path),
    )


def _pivot_axis_labels(rows, axis_specs, model_cls):
    """Collect distinct ``(value, label)`` tuples for each axis spec.

    ``rows`` is the output of ``read_group``. ``axis_specs`` is the
    ordered list of ``"field"`` / ``"field:trunc"`` strings used in
    that read_group call (in the order they were passed).

    Returns a list, one entry per axis level, of ordered lists of
    ``{"value": <raw>, "label": <human>}`` dicts. Each axis is sorted
    by raw value with ``None`` floated to the end so missing-value
    rows always appear last regardless of which combinations the
    underlying read_group happened to surface first.
    """
    out: list[list[dict]] = []
    for spec in axis_specs:
        if ":" in spec:
            fname, trunc = spec.split(":", 1)
        else:
            fname, trunc = spec, None
        label_key = f"{spec}__label"
        seen: dict = {}
        for r in rows:
            raw = r.get(spec)
            if raw in seen:
                continue
            if label_key in r and r[label_key] is not None:
                label = str(r[label_key])
            else:
                label = _format_group_label(raw, fname, trunc, model_cls)
            seen[raw] = label
        # Sort by the raw value; None always last (we can't compare it
        # against other types in Python 3). Falls back to string
        # comparison so heterogenous types still produce a stable
        # ordering instead of a TypeError.
        def _key(v):
            return (v is None, _sort_key(v))
        ordered_values = sorted(seen.keys(), key=_key)
        out.append([{"value": v, "label": seen[v]} for v in ordered_values])
    return out


def _sort_key(v):
    """Coerce a value to a comparable sort key.

    Used by ``_pivot_axis_labels`` so axes with mixed-typish content
    (e.g. an Integer + the occasional NULL → None) still produce a
    stable sort order in Python 3 where ``None < 0`` raises TypeError.
    """
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return (0, float(v))
    return (1, str(v))


def _measure_label(spec: str, model_cls) -> str:
    """Human label for a measure spec ("field:agg" / "__count")."""
    if spec == "__count":
        return "Count"
    if ":" in spec:
        fname, agg = spec.split(":", 1)
    else:
        fname, agg = spec, "sum"
    f = model_cls._fields.get(fname)
    base = (f.string if f and f.string else fname) if f else fname
    return f"{base} ({agg})"


def _format_pivot_cell(value, measure_spec: str) -> str:
    """Format one cell value as a string for display.

    Counts render as integers, everything else as either a float with
    two decimals or its native ``str()`` form. ``None`` (no rows
    matched the row × col intersection) renders as an em dash.
    """
    if value is None:
        return "—"
    if measure_spec == "__count":
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def render_pivot_page(
    view,
    env,
    *,
    search: str = "",
    filters: str = "",
    current_path: str | None = None,
) -> str:
    """Render a pivot view: a cross-tab table aggregating one or more
    measures over the cartesian product of ``row_groupby`` × ``col_groupby``.

    Single ``read_group`` call covers the whole table: we ask for all
    rows and cols together, then pivot the flat result into a nested
    HTML matrix in Python. Row totals (per row) and a grand-total
    column / row are computed cell-by-cell — Postgres' ROLLUP could
    do it server-side but for the cardinalities a pivot is useful at
    (a few rows × a few cols × few measures), client-side aggregation
    is plenty fast and avoids burning round-trips.
    """
    from .views import resolve_arch

    arch = resolve_arch(view)
    row_specs = list(arch.get("row_groupby") or [])
    col_specs = list(arch.get("col_groupby") or [])
    measure_specs = list(arch.get("measures") or ["__count"])
    static_domain = list(arch.get("domain") or [])

    model_cls = env.registry[view.model]
    Model = env[view.model]

    pseudo_fields_spec = [
        {"name": n} for n, f in model_cls._fields.items() if f.is_stored
    ]
    domain = list(static_domain)
    if search:
        domain.extend(_build_search_domain(model_cls, pseudo_fields_spec, search))
    if filters:
        domain.extend(_parse_filters(model_cls, pseudo_fields_spec, filters))

    flat_rows = Model.read_group(
        domain,
        groupby=row_specs + col_specs,
        measures=measure_specs,
    )

    # Order is "first seen in the read_group result" per axis spec —
    # consistent because read_group's default ORDER BY mirrors the
    # group-key order we requested.
    row_axes = _pivot_axis_labels(flat_rows, row_specs, model_cls)
    col_axes = _pivot_axis_labels(flat_rows, col_specs, model_cls)

    # Index flat_rows by (row_key_tuple, col_key_tuple) for O(1) cell
    # lookup. Each cell holds the per-measure dict.
    cell_index: dict[tuple, dict] = {}
    for r in flat_rows:
        row_key = tuple(r.get(s) for s in row_specs)
        col_key = tuple(r.get(s) for s in col_specs)
        cell_index[(row_key, col_key)] = {
            m: r.get(m) for m in measure_specs
        }

    # Materialize the cartesian product of row / col axes. With more
    # than ~5k cells the page gets unwieldy; we trust the view author
    # to keep cardinalities sane (Odoo applies the same convention).
    def _product(axes):
        from itertools import product as _ip
        if not axes:
            return [()]
        return list(_ip(*[[entry["value"] for entry in a] for a in axes]))

    row_combos = _product(row_axes)
    col_combos = _product(col_axes)

    # Headers: one row per col_groupby level, repeating each parent
    # label across its children for the right colspan. The first
    # column carries the row-axis label; the trailing column is
    # the "Total" grand-sum.
    header_levels: list[list[dict]] = []
    if col_axes:
        for level_idx, level in enumerate(col_axes):
            # The colspan at this level is the product of sizes of
            # the levels *below* it.
            below = col_axes[level_idx + 1:]
            span_per_label = 1
            for b in below:
                span_per_label *= max(1, len(b))
            # Repeat each label as many times as the parent product
            # above (group-by-group). The label here repeats once per
            # combination of levels *above*, but visually we collapse
            # consecutive duplicates into a single th with colspan.
            cells = []
            for entry in level:
                cells.append({
                    "label": entry["label"],
                    "colspan": span_per_label * len(measure_specs),
                })
            header_levels.append(cells)
    # Final header row: measure labels, one per leaf-col entry plus
    # the grand-total column.
    measure_label_row: list[dict] = []
    for _combo in col_combos:
        for m in measure_specs:
            measure_label_row.append({
                "label": _measure_label(m, model_cls),
                "colspan": 1,
            })
    # Grand total column header — one cell spanning len(measure_specs)
    # at the right side. We emit it on each level, and the measure
    # row gets one entry per measure under it.
    grand_header = {
        "label": "Total",
        "colspan": len(measure_specs),
    }

    # Body rows: nested by row_groupby. For first iteration we render
    # a flat list (no row indentation between levels — that's a polish
    # task) but still surface row totals.
    body_rows: list[dict] = []
    for row_combo in row_combos:
        row_labels: list[str] = []
        for level_idx, key_val in enumerate(row_combo):
            entries = row_axes[level_idx]
            label = next(
                (e["label"] for e in entries if e["value"] == key_val),
                str(key_val),
            )
            row_labels.append(label)
        cells: list[dict] = []
        # Per-measure row totals (summed across columns).
        row_totals: dict[str, float | int] = {m: 0 for m in measure_specs}
        for col_combo in col_combos:
            measures_at_cell = cell_index.get((row_combo, col_combo))
            for m in measure_specs:
                value = measures_at_cell.get(m) if measures_at_cell else None
                cells.append({
                    "value": value,
                    "display": _format_pivot_cell(value, m),
                })
                if value is not None:
                    try:
                        row_totals[m] += float(value)
                    except (TypeError, ValueError):
                        pass
        # Grand-total cells (rightmost) — one per measure.
        for m in measure_specs:
            total = row_totals[m]
            cells.append({
                "value": total,
                "display": _format_pivot_cell(total, m),
                "is_total": True,
            })
        body_rows.append({"labels": row_labels, "cells": cells})

    # Column-grand-total row at the bottom.
    col_totals: list[dict] = []
    grand_grand: dict[str, float | int] = {m: 0 for m in measure_specs}
    for col_combo in col_combos:
        for m in measure_specs:
            running: float | int = 0
            for row_combo in row_combos:
                measures_at_cell = cell_index.get((row_combo, col_combo))
                if measures_at_cell is None:
                    continue
                v = measures_at_cell.get(m)
                if v is None:
                    continue
                try:
                    running += float(v)
                except (TypeError, ValueError):
                    pass
            col_totals.append({
                "value": running,
                "display": _format_pivot_cell(running, m),
                "is_total": True,
            })
            grand_grand[m] += running
    for m in measure_specs:
        col_totals.append({
            "value": grand_grand[m],
            "display": _format_pivot_cell(grand_grand[m], m),
            "is_total": True,
        })

    # Row-axis header column titles ("Stage" / "Salesperson"…).
    row_axis_titles: list[str] = []
    for spec in row_specs:
        fname = spec.split(":", 1)[0]
        f = model_cls._fields.get(fname)
        label = (f.string if f and f.string else fname) if f else fname
        if ":" in spec:
            label += f" ({spec.split(':', 1)[1]})"
        row_axis_titles.append(label)

    page_title = _view_title(view, arch)

    # Build field lists for toolbar dropdowns (same logic as render_graph_page).
    from .fields import Boolean, Date, Datetime, Float, Integer, Many2one

    groupable_fields: list[dict] = []
    measurable_fields: list[dict] = [{"value": "__count", "label": "Count"}]
    for fname, field in model_cls._fields.items():
        if not field.is_stored or field.private:
            continue
        label = field.string or fname
        ft = type(field).__name__
        if isinstance(field, (Many2one, Date, Datetime)):
            groupable_fields.append({"value": fname, "label": label, "type": ft})
            if isinstance(field, (Date, Datetime)):
                for trunc in ("day", "week", "month", "quarter", "year"):
                    groupable_fields.append({
                        "value": f"{fname}:{trunc}",
                        "label": f"{label} ({trunc})",
                        "type": ft,
                    })
        elif not isinstance(field, (Float, Boolean)):
            groupable_fields.append({"value": fname, "label": label, "type": ft})
        if isinstance(field, (Integer, Float)):
            measurable_fields.append({
                "value": f"{fname}:sum",
                "label": f"{label} (sum)",
                "type": ft,
            })
            measurable_fields.append({
                "value": f"{fname}:avg",
                "label": f"{label} (avg)",
                "type": ft,
            })

    template = _env.get_template("pivot.html")
    return template.render(
        view=view,
        row_axis_titles=row_axis_titles,
        header_levels=header_levels,
        measure_label_row=measure_label_row,
        grand_header=grand_header,
        body_rows=body_rows,
        col_totals=col_totals,
        measure_count=len(measure_specs),
        col_combos_count=len(col_combos),
        search=search,
        filters=filters,
        page_title=page_title,
        subtitle=(
            f"{len(row_combos)} row{'s' if len(row_combos) != 1 else ''}"
            f" × {max(1, len(col_combos))} column{'s' if len(col_combos) != 1 else ''}"
        ),
        view_switcher=_other_views_for_model(env, view),
        groupable_fields=groupable_fields,
        measurable_fields=measurable_fields,
        init_row_groupby=",".join(row_specs),
        init_col_groupby=",".join(col_specs),
        init_measures=",".join(measure_specs),
        **layout_context(env, current_path),
    )


def _find_form_view(view, env):
    """Return the name of the first form view for the same model+module,
    or None if no such view is registered."""
    if "ir.ui.view" not in env.registry:
        return None
    matches = _search_ui_views(
        env,
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
    matches = _search_ui_views(
        env,
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
    matches = _search_ui_views(
        env,
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
    bc_stack: list[tuple[str, str]] | None = None,
    current_path: str | None = None,
) -> str:
    """Full HTML page for a list view: heading, toolbar, sortable DataTable
    with server-side search / ordering / pagination."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    form_view_name = arch.get("form_view") or _find_form_view(view, env)
    record_href = arch.get("record_href")
    create_href = arch.get("create_href")

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
    list_nav_query = encode_view_nav_query(
        view.module,
        view.name,
        search=search,
        order=order,
        filters=filters,
        group_by=safe_group_by,
        page=page,
        page_size=page_size,
        bc_stack=bc_stack,
    )
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
        record_href=record_href,
        create_href=create_href,
        list_nav_query=list_nav_query,
        page_title=page_title,
        # No record-count subtitle on list views — the pager footer
        # already shows the total. Pass an empty string so existing
        # ``{% if subtitle %}`` checks just skip.
        subtitle="",
        view_switcher=_other_views_for_model(
            env,
            view,
            bc_stack=bc_stack,
            search=search,
            order=order,
            filters=filters,
            group_by=safe_group_by,
            page=page,
            page_size=page_size,
        ),
        bc_param=format_bc_param(bc_stack or []),
        access=template_access(env, view.model),
        **layout_context(env, current_path, leaf_label=page_title),
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
    bc_stack: list[tuple[str, str]] | None = None,
) -> str:
    """Table body fragment + oob pagination — used by HTMX control swaps."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    fields_spec = arch.get("fields", [])
    form_view_name = arch.get("form_view") or _find_form_view(view, env)
    record_href = arch.get("record_href")
    create_href = arch.get("create_href")

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

    list_nav_query = encode_view_nav_query(
        view.module,
        view.name,
        search=search,
        order=order,
        filters=filters,
        group_by=safe_group_by,
        page=page,
        page_size=page_size,
        bc_stack=bc_stack,
    )
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
        record_href=record_href,
        create_href=create_href,
        list_nav_query=list_nav_query,
        access=template_access(env, view.model),
    )


def _load_account_user(env):
    """Return the signed-in ``res.users`` row (primed for shell/profile reads)."""
    if env.uid is None:
        return None
    env.prime_current_user_cache()
    user = env["res.users"].browse(env.uid)
    if not env["res.users"].search([("id", "=", env.uid)], limit=1):
        return None
    user.ensure_one()
    return user


def _account_profile_context(user) -> dict:
    # sudo: self-service profile reads the user's own row + related
    # company / groups without requiring broad res.users grants.
    user = user.sudo()
    company_name = ""
    if user.company_id:
        company_name = user.company_id.name or ""
    groups = [g.name for g in user.group_ids] if user.group_ids else []
    return {
        "name": user.name or "",
        "login": user.login or "",
        "company_name": company_name,
        "groups": groups,
        "avatar_widget": _render_image_widget(
            user.avatar_url or "",
            {"name": "avatar_url"},
            readonly=False,
        ),
    }


def _account_layout_context(
    env, current_path: str | None = None, *, leaf_label: str | None = None
) -> dict:
    """Shell context for account pages — top bar only, no admin sidebar."""
    ctx = layout_context(env, current_path, leaf_label)
    # Account URLs are outside the menu tree — skip menu-derived crumbs.
    ctx["breadcrumbs"] = []
    ctx["use_sidebar"] = False
    return ctx


def render_account_profile_page(
    env,
    *,
    current_path: str | None = None,
    error: str = "",
    success: bool = False,
    form_overrides: dict | None = None,
) -> str:
    """Self-service profile editor (name + avatar) for the signed-in user."""
    user = _load_account_user(env)
    if user is None:
        raise ValueError("No signed-in user")
    ctx = _account_profile_context(user)
    if form_overrides:
        for key in ("name",):
            if key in form_overrides:
                ctx[key] = form_overrides[key]
        if "avatar_url" in form_overrides:
            ctx["avatar_widget"] = _render_image_widget(
                form_overrides["avatar_url"] or "",
                {"name": "avatar_url"},
                readonly=False,
            )
    template = _env.get_template("account_profile.html")
    return template.render(
        error=error,
        success=success,
        **ctx,
        **_account_layout_context(env, current_path, leaf_label="My profile"),
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
        **_account_layout_context(env, current_path, leaf_label="Change password"),
    )


def render_admin_password_reset_page(
    env,
    user,
    *,
    current_path: str | None = None,
    csrf_token: str = "",
    error: str = "",
    success: bool = False,
) -> str:
    """Admin-driven password reset for *another* user.

    No current-password check — by construction this page is reached
    via the ``res.users`` form's "Reset password" action, which the
    ORM already gated on ``perm_write`` for the model. Self-service
    (the user changing their own password with their current one)
    still lives at ``/web/account/password``.
    """
    template = _env.get_template("admin_password_reset.html")
    return template.render(
        user=user,
        error=error,
        success=success,
        csrf_token=csrf_token,
        **layout_context(env, current_path),
    )


def render_login_page(
    *,
    error: str = "",
    next: str = "",
    prefill_login: str = "",
    csrf_token: str = "",
    env=None,
) -> str:
    from pyvelm.branding import branding_context

    template = _env.get_template("login.html")
    ctx = branding_context(env) if env is not None else branding_context(None)
    ctx.update(
        {
            "error": error,
            "next": next,
            "prefill_login": prefill_login,
            "csrf_token": csrf_token,
        }
    )
    return template.render(**ctx)


def _format_stat_value(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return str(value)
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.2f}"


def _resolve_dashboard_colspan(
    colspan,
    grid_columns: int,
    *,
    default: int = 1,
) -> int:
    """Map widget ``colspan`` (int or ``'full'``) to a grid track count."""
    if isinstance(colspan, str) and colspan.lower() == "full":
        return grid_columns
    try:
        n = int(colspan if colspan is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, grid_columns))


def _dashboard_widget_visible(env, raw: dict, *, source_module: str) -> bool:
    """Return whether the current user may see a dashboard widget."""
    wtype = raw.get("type")
    perm = (raw.get("perm") or "read").strip() or "read"
    if wtype == "link":
        model = (raw.get("subtitle") or "").strip()
        if model and model in env.registry:
            link_perm = (raw.get("perm") or "write").strip() or "write"
            return env.has_access(model, link_perm)
        return True
    model = raw.get("model")
    if not model and raw.get("view"):
        mod, vname = _parse_view_ref(raw["view"], source_module)
        view_type = "graph" if wtype == "chart" else "list"
        view = _find_ui_view(env, mod, vname, view_type)
        model = view.model if view else None
    if model and model in env.registry:
        return env.has_access(model, perm)
    return True


def _materialize_dashboard_widgets(
    env, widgets: list[dict], source_module: str
) -> list[dict]:
    """Turn declarative widget specs into template-ready dicts."""
    from types import SimpleNamespace

    from .views import resolve_arch

    out: list[dict] = []
    for raw in widgets:
        if not _dashboard_widget_visible(env, raw, source_module=source_module):
            continue
        wtype = raw.get("type")
        wid = raw.get("id") or f"widget_{len(out)}"
        default_span = 2 if wtype == "chart" else 1
        colspan = raw.get("colspan", default_span)
        title = raw.get("title") or ""
        base = {"type": wtype, "id": wid, "colspan": colspan, "title": title}

        if wtype == "link":
            out.append({
                **base,
                "subtitle": raw.get("subtitle") or "",
                "description": raw.get("description") or "",
                "url": raw.get("url") or "#",
            })
            continue

        if wtype == "stat":
            model = raw["model"]
            domain = list(raw.get("domain") or [])
            measure = raw.get("measure") or "__count"
            Model = env[model]
            if measure == "__count":
                value = Model.search_count(domain)
            else:
                rows = Model.read_group(domain, groupby=[], measures=[measure])
                value = rows[0].get(measure, 0) if rows else 0
            out.append({
                **base,
                "value_display": _format_stat_value(value),
                "href": raw.get("href"),
            })
            continue

        if wtype == "chart":
            view_ref = raw.get("view")
            if view_ref:
                mod, vname = _parse_view_ref(view_ref, source_module)
                gv = _find_ui_view(env, mod, vname, "graph")
                if not gv:
                    out.append({**base, "error": f"Graph view {mod}/{vname} not found"})
                    continue
                garch = resolve_arch(gv)
                model = gv.model
                groupby = garch["groupby"]
                measure = garch.get("measure") or "__count"
                chart = garch.get("chart", "bar")
                domain = list(garch.get("domain") or [])
                if not title:
                    title = _view_title(gv, garch)
            else:
                model = raw["model"]
                groupby = raw["groupby"]
                measure = raw.get("measure") or "__count"
                chart = raw.get("chart", "bar")
                domain = list(raw.get("domain") or [])
            try:
                chart_data = _graph_chart_data(
                    env,
                    model=model,
                    groupby=groupby,
                    measure=measure,
                    chart=chart,
                    domain=domain,
                )
                out.append({**base, "title": title, "chart_data": chart_data})
            except Exception as exc:
                out.append({**base, "error": str(exc)})
            continue

        if wtype == "table":
            view_ref = raw.get("view")
            list_mod = source_module
            list_name = ""
            more_href = raw.get("more_href")
            if view_ref:
                list_mod, list_name = _parse_view_ref(view_ref, source_module)
                lv = _find_ui_view(env, list_mod, list_name, "list")
                if not lv:
                    out.append({**base, "error": f"List view {list_mod}/{list_name} not found"})
                    continue
                larch = resolve_arch(lv)
                model = lv.model
                fields_spec = list(larch.get("fields") or [])
                if not title:
                    title = _view_title(lv, larch)
                if not more_href:
                    more_href = f"/web/views/{list_mod}/{list_name}"
            else:
                model = raw["model"]
                fields_spec = list(raw.get("fields") or [])
            column_names = raw.get("columns")
            if column_names:
                fields_spec = _filter_fields_spec(fields_spec, list(column_names))
            domain = list(raw.get("domain") or [])
            limit = int(raw.get("limit") or 10)
            model_cls = env.registry[model]
            fields_spec = _enrich_specs_for_edit(env, model_cls, fields_spec)
            headers = _field_headers(model_cls, fields_spec)
            safe_ord = _safe_order(fields_spec, raw.get("order") or "")
            recs = env[model].search(domain, limit=limit, order=safe_ord)
            pseudo = SimpleNamespace(
                model=model, module=list_mod, name=list_name or "inline"
            )
            rows = _build_rows(pseudo, recs, fields_spec)
            out.append({
                **base,
                "title": title,
                "headers": headers,
                "rows": rows,
                "more_href": more_href,
            })
            continue

        out.append({**base, "error": f"Unknown widget type {wtype!r}"})
    return out


def render_dashboard_page(
    view,
    env,
    *,
    current_path: str | None = None,
) -> str:
    """Render a declarative dashboard from ``view_type="dashboard"`` arch."""
    from .views import resolve_arch

    arch = resolve_arch(view)
    page_title = arch.get("title") or _view_title(view, arch)
    subtitle = arch.get("subtitle") or ""
    grid_columns = max(1, min(6, int(arch.get("columns") or 2)))
    widgets = _materialize_dashboard_widgets(
        env, list(arch.get("widgets") or []), view.module
    )
    for w in widgets:
        w["colspan"] = _resolve_dashboard_colspan(w.get("colspan"), grid_columns)
    chart_widgets = [
        w for w in widgets
        if w.get("type") == "chart" and w.get("chart_data")
    ]
    template = _env.get_template("dashboard.html")
    ctx = layout_context(env, current_path, leaf_label=page_title) if env else {}
    return template.render(
        page_title=page_title,
        subtitle=subtitle,
        grid_columns=grid_columns,
        widgets=widgets,
        chart_widgets=chart_widgets,
        **ctx,
    )


def render_admin_page(env=None, current_path: str | None = None) -> str:
    if env is not None and "ir.ui.view" in env.registry:
        dash = _search_ui_views(
            env,
            [
                ("module", "=", "admin"),
                ("name", "=", "home"),
                ("view_type", "=", "dashboard"),
            ],
            limit=1,
        )
        if dash:
            return render_dashboard_page(dash, env, current_path=current_path)
    cards = [
        {
            "title": "Groups",
            "subtitle": "res.groups",
            "description": "Manage permission groups and their members.",
            "url": "/web/views/admin/group.list",
            "perm": "write",
        },
        {
            "title": "Users",
            "subtitle": "res.users",
            "description": "Create and manage operator accounts.",
            "url": "/web/views/admin/user.list",
            "perm": "write",
        },
        {
            "title": "Access Control",
            "subtitle": "ir.model.access",
            "description": "Grant CRUD permissions per model and group.",
            "url": "/web/views/admin/access.list",
            "perm": "write",
        },
        {
            "title": "Record Rules",
            "subtitle": "ir.rule",
            "description": "Define row-level security using domain filters.",
            "url": "/web/views/admin/rule.list",
            "perm": "write",
        },
        {
            "title": "Companies",
            "subtitle": "res.company",
            "description": "Manage companies and multi-tenant configuration.",
            "url": "/web/views/admin/company.list",
            "perm": "write",
        },
        {
            "title": "Partners",
            "subtitle": "res.partner",
            "description": "Browse and manage partners for the current company.",
            "url": "/web/views/partners/partner.list",
            "perm": "read",
        },
    ]
    if env is not None:
        cards = [
            c
            for c in cards
            if env.has_access(
                c["subtitle"],
                (c.get("perm") or "read").strip() or "read",
            )
        ]
    template = _env.get_template("admin.html")
    ctx = layout_context(env, current_path) if env is not None else {}
    if env is not None:
        ctx["subtitle"] = "Framework configuration and security."
    return template.render(cards=cards, **ctx)


def _home_breadcrumb() -> dict:
    from pyvelm.home import home_url

    return {"label": "Home", "href": home_url()}


def render_landing_page(env=None, *, current_path: str | None = None) -> str:
    """Public marketing-style entry page at ``/`` (no app sidebar)."""
    from .branding import branding_context
    from .home import home_url, login_url

    brand = branding_context(env)
    app = brand.get("app_name") or "pyvelm"
    template = _env.get_template("landing.html")
    tagline = (brand.get("app_tagline") or "").strip() or (
        "Sign in to manage your data, workflows, and team — or explore the demo modules."
    )
    return template.render(
        brand=brand,
        headline=f"Welcome to {app}",
        tagline=tagline,
        get_started_href=login_url(),
        sign_in_href=login_url(),
        home_url=home_url(),
        current_path=current_path or "/",
    )


def render_home_page(env, *, current_path: str | None = None) -> str:
    """Render ``PYVELM_HOME_URL`` when it points at a built-in view path."""
    from .home import home_url

    path = home_url()
    current_path = current_path or path
    if path in ("/web/admin", "/web/admin/"):
        return render_admin_page(env, current_path=current_path)
    if path.startswith("/web/views/"):
        parts = path.rstrip("/").split("/")
        if len(parts) >= 5 and parts[1] == "web" and parts[2] == "views":
            module, name = parts[3], parts[4]
            view = _load_ui_view(env.sudo(), module, name)
            if view is None:
                raise ValueError(f"Home view {module}/{name!r} not found")
            if view.view_type == "dashboard":
                return render_dashboard_page(view, env, current_path=current_path)
            if view.view_type == "list":
                return render_list_page(view, env, current_path=current_path)
            if view.view_type == "kanban":
                return render_kanban_page(view, env, current_path=current_path)
            if view.view_type == "graph":
                return render_graph_page(view, env, current_path=current_path)
            raise ValueError(
                f"Home view {module}/{name!r} has type {view.view_type!r}; "
                "use dashboard, list, kanban, or graph"
            )
    raise ValueError(
        f"PYVELM_HOME_URL={path!r} cannot be rendered inline — use a /web/views/… "
        "path or leave the default /web/admin"
    )


# Routes that use the top-nav shell (no admin sidebar) — access denied
# should match, e.g. feedback capture and account self-service pages.
_MINIMAL_ACCESS_DENIED_PREFIXES: tuple[str, ...] = (
    "/web/feedback_signals/",
    "/web/account/",
)


def access_denied_use_sidebar(current_path: str | None) -> bool:
    """Return whether the access-denied page should include the app sidebar."""
    if not current_path:
        return True
    path = current_path.split("?", 1)[0]
    return not any(path.startswith(prefix) for prefix in _MINIMAL_ACCESS_DENIED_PREFIXES)


# ---------------------------------------------------------------------------
# Generic styled error pages (4xx / 5xx)
# ---------------------------------------------------------------------------

# Heroicons (outline) SVG path stubs keyed by status code. Anything
# not listed falls back to the generic ``warning`` glyph. Keep this
# narrow — every "exotic" status family rolls up to its leading digit.
_ERROR_ICON_WARNING = (
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71'
    'c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5'
    '-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>'
)
_ERROR_ICON_DETAILS: dict[int, dict] = {
    400: {
        "title": "Bad request",
        "message": "The request didn't look right. Check your input and try again.",
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": _ERROR_ICON_WARNING,
    },
    401: {
        "title": "Sign in required",
        "message": "You need to sign in to view this page.",
        "icon_bg": "bg-brand-softer",
        "icon_fg": "text-fg-brand",
        "icon_path": (
            '<path stroke-linecap="round" stroke-linejoin="round" '
            'd="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 '
            '2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 '
            '2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"/>'
        ),
    },
    403: {
        "title": "Access denied",
        "message": (
            "You don't have permission to view this page or perform this "
            "action. If you think this is a mistake, contact your administrator."
        ),
        "icon_bg": "bg-danger-soft",
        "icon_fg": "text-fg-danger",
        "icon_path": (
            '<path stroke-linecap="round" stroke-linejoin="round" '
            'd="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 '
            '2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 '
            '2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"/>'
        ),
    },
    404: {
        "title": "Page not found",
        "message": "We couldn't find that page. The link may be broken or the record removed.",
        "icon_bg": "bg-neutral-tertiary",
        "icon_fg": "text-body-subtle",
        "icon_path": (
            '<path stroke-linecap="round" stroke-linejoin="round" '
            'd="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 '
            '1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.997'
            '-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z"/>'
        ),
    },
    405: {
        "title": "Method not allowed",
        "message": "That action isn't supported on this endpoint.",
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": _ERROR_ICON_WARNING,
    },
    422: {
        "title": "Validation failed",
        "message": "Some of the data you submitted didn't pass validation.",
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": _ERROR_ICON_WARNING,
    },
    429: {
        "title": "Too many requests",
        "message": (
            "You're going a bit fast. Please wait a moment before trying again."
        ),
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": (
            '<path stroke-linecap="round" stroke-linejoin="round" '
            'd="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"/>'
        ),
    },
    500: {
        "title": "Something went wrong",
        "message": (
            "An unexpected error occurred while processing your request. "
            "Try again, and if it keeps happening, contact your administrator."
        ),
        "icon_bg": "bg-danger-soft",
        "icon_fg": "text-fg-danger",
        "icon_path": _ERROR_ICON_WARNING,
    },
    501: {
        "title": "Not implemented",
        "message": "This action hasn't been wired up on the server yet.",
        "icon_bg": "bg-neutral-tertiary",
        "icon_fg": "text-body-subtle",
        "icon_path": _ERROR_ICON_WARNING,
    },
    502: {
        "title": "Bad gateway",
        "message": "An upstream service didn't respond as expected. Try again shortly.",
        "icon_bg": "bg-danger-soft",
        "icon_fg": "text-fg-danger",
        "icon_path": _ERROR_ICON_WARNING,
    },
    503: {
        "title": "Service unavailable",
        "message": "The server is temporarily unable to handle the request. Try again shortly.",
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": _ERROR_ICON_WARNING,
    },
    504: {
        "title": "Gateway timeout",
        "message": "The server took too long to respond. Try again shortly.",
        "icon_bg": "bg-warning-soft",
        "icon_fg": "text-fg-warning",
        "icon_path": _ERROR_ICON_WARNING,
    },
}


def _error_defaults(status_code: int) -> dict:
    """Look up the title/message/icon defaults for a given status code,
    falling back to a generic 4xx / 5xx flavour for codes without an
    explicit entry."""
    if status_code in _ERROR_ICON_DETAILS:
        return dict(_ERROR_ICON_DETAILS[status_code])
    family = status_code // 100
    if family == 4:
        return {
            "title": "Request error",
            "message": "We couldn't complete your request.",
            "icon_bg": "bg-warning-soft",
            "icon_fg": "text-fg-warning",
            "icon_path": _ERROR_ICON_WARNING,
        }
    return {
        "title": "Server error",
        "message": "An unexpected error occurred. Try again shortly.",
        "icon_bg": "bg-danger-soft",
        "icon_fg": "text-fg-danger",
        "icon_path": _ERROR_ICON_WARNING,
    }


def render_error_page(
    env,
    *,
    status_code: int,
    title: str | None = None,
    message: str | None = None,
    detail: str | None = None,
    current_path: str | None = None,
    use_sidebar: bool | None = None,
    retry_after: int | None = None,
) -> str:
    """Full-page styled error screen for any 4xx/5xx status.

    Title / message default per status code (see ``_ERROR_ICON_DETAILS``);
    pass ``title`` / ``message`` to override. ``detail`` carries a small
    diagnostic line (e.g. the raw exception message). ``retry_after``
    renders a live countdown — used by 429 responses.

    The sidebar / top-nav choice mirrors :func:`render_access_denied_page`
    so error pages on account / feedback URLs stay minimal.
    """
    template = _env.get_template("error.html")
    defaults = _error_defaults(int(status_code))
    if title is not None:
        defaults["title"] = title
    if message is not None:
        defaults["message"] = message
    if use_sidebar is None:
        use_sidebar = access_denied_use_sidebar(current_path)
    ctx = merge_template_context(env, current_path)
    ctx.update(defaults)
    ctx["status_code"] = int(status_code)
    ctx["detail"] = detail
    ctx["retry_after"] = int(retry_after) if retry_after else None
    if not use_sidebar:
        ctx["use_sidebar"] = False
        ctx["breadcrumbs"] = []
    return template.render(**ctx)


def render_access_denied_page(
    env,
    *,
    detail: str | None = None,
    current_path: str | None = None,
    use_sidebar: bool | None = None,
) -> str:
    """Full-page "Access denied" screen inside the app shell.

    Served by the HTTP layer when an authenticated user hits a page or
    action they lack the grant for — read access opens pages, so this is
    the fallback for the genuinely-forbidden case (e.g. a deep-linked
    edit/create URL). `detail` carries the raw ``PermissionError``
    message for the small diagnostic line; pass ``None`` to omit it.

    When ``use_sidebar`` is false (auto for feedback capture / account URLs),
    the page uses the same top-nav-only layout as those flows.
    """
    template = _env.get_template("access_denied.html")
    if use_sidebar is None:
        use_sidebar = access_denied_use_sidebar(current_path)
    ctx = merge_template_context(env, current_path, detail=detail)
    if not use_sidebar:
        ctx["use_sidebar"] = False
        ctx["breadcrumbs"] = []
    return template.render(**ctx)


def _apps_catalog(env, module_roots: list) -> list[dict]:
    """Discover every module under `module_roots`, join with installed-
    version rows from `ir_module`, and return one dict per module.

    Each entry shape:
        {
          "name": str,
          "display_name": str,
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
        # Optional catalog visibility gate (UI only): hide modules the user
        # cannot reach. Mirrors sidebar menu gating but is recordless.
        cam = (spec.catalog_access_model or "").strip() or None
        if cam:
            cap = (spec.catalog_access_perm or "").strip() or "read"
            if not env.has_access(cam, cap):
                continue
            pol = (spec.catalog_access_policy or "").strip() or None
            if pol and not env.can(cam, pol, perm=cap, model=cam):
                continue
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
                "display_name": spec.display_name,
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
    catalog.sort(key=lambda c: (c["display_name"].lower(), c["name"]))
    return catalog


def _apps_catalog_entry(
    env, module_roots: list, name: str
) -> dict | None:
    for entry in _apps_catalog(env, module_roots):
        if entry["name"] == name:
            return entry
    return None


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
    """Re-sync an installed module: reload models + DATA from disk,
    apply additive schema (``_setup_table`` + autogen diff), run
    version-gap migrations when the manifest version increased, and
    upsert views / menus.
    """
    from . import loader as _loader

    specs = _loader.discover(module_roots)
    if target_name not in specs:
        raise ValueError(f"Unknown module {target_name!r}")
    spec = specs[target_name]
    current = _loader._installed_version(env, target_name)
    if current is None:
        raise ValueError(
            f"Module {target_name!r} is not installed — use Install first."
        )
    _loader.reload_models(spec, env.registry)
    outcomes = _loader.install([spec], env)
    detail = outcomes[0] if outcomes else {}
    parts = [
        f"Synced {target_name} ({spec.version_str})",
        detail.get("schema", ""),
        detail.get("views", ""),
        detail.get("menus", ""),
    ]
    message = " | ".join(p for p in parts if p)
    return {
        "ok": True,
        "upgraded": [target_name],
        "message": message,
        "detail": detail,
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
    """Apps catalog at `/web/apps` — grid of module cards."""
    env.check_can("res.users", "view_any", perm="read")
    catalog = _apps_catalog(env, module_roots)
    summary = {
        "total": len(catalog),
        "installed": sum(1 for c in catalog if c["state"] == "installed"),
        "to_upgrade": sum(1 for c in catalog if c["state"] == "to_upgrade"),
        "uninstalled": sum(1 for c in catalog if c["state"] == "uninstalled"),
    }
    categories = sorted({c["category"] for c in catalog})
    template = _env.get_template("apps.html")
    return template.render(
        catalog=catalog,
        categories=categories,
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


def render_apps_detail_page(
    env, module_roots: list, name: str, current_path: str | None = None
) -> str | None:
    """Per-module detail at `/web/apps/<name>`. Returns None if unknown."""
    env.check_can("res.users", "view_any", perm="read")
    app = _apps_catalog_entry(env, module_roots, name)
    if app is None:
        return None
    ctx = layout_context(env, current_path, leaf_label=app["display_name"])
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Apps", "href": "/web/apps"},
        {"label": app["display_name"], "href": None},
    ]
    template = _env.get_template("apps_detail.html")
    return template.render(
        app=app,
        page_title=app["display_name"],
        subtitle=app["name"],
        **ctx,
    )


def render_report_run_page(report_rec, env, current_path: str | None = None) -> str:
    """Interactive report run page with parameter form and live preview."""
    from .reports.service import can_run_report, definition_dict

    if not can_run_report(env, report_rec):
        raise PermissionError("Not allowed to run this report")
    defn = definition_dict(report_rec)
    parameters = defn.get("parameters") or []
    initial_params = {p["name"]: "" for p in parameters}
    ctx = layout_context(env, current_path, leaf_label=report_rec.name)
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Reports", "href": "/web/records/reports/report.list"},
        {"label": report_rec.name, "href": None},
    ]
    template = _env.get_template("report_run.html")
    return template.render(
        report={"id": report_rec.id, "name": report_rec.name, "description": report_rec.description or "", "root_model": report_rec.root_model},
        parameters=parameters,
        query_suffix="",
        alpine_config={"reportId": report_rec.id, "initialParams": initial_params},
        page_title=report_rec.name,
        subtitle=f"Model: {report_rec.root_model}",
        **ctx,
    )


def render_report_builder_page(
    env, report_rec=None, current_path: str | None = None,
) -> str:
    """Visual report builder — create or edit."""
    import json as _json
    from .reports.compile import parse_definition

    page_title = "New report"
    alpine_cfg: dict = {
        "reportId": None,
        "reportMode": "detail",
        "meta": {
            "name": "",
            "description": "",
            "root_model": "",
            "row_limit": 10000,
            "schedule_active": False,
            "output_format": "xlsx",
        },
        "definition": {
            "version": 1,
            "root": "",
            "columns": [],
            "filters": [],
            "parameters": [],
            "parameter_filters": [],
            "order": [],
        },
        "columnSort": {},
        "orderRules": [],
    }
    if report_rec is not None:
        report_rec.ensure_one()
        page_title = report_rec.name
        defn = parse_definition(report_rec.definition)
        filters_ui = []
        for leaf in defn.get("filters") or []:
            if isinstance(leaf, (list, tuple)) and len(leaf) >= 3:
                v = leaf[2]
                if isinstance(v, list):
                    v = ", ".join(str(x) for x in v)
                filters_ui.append({"field": leaf[0], "op": leaf[1], "value": str(v)})
        param_links: dict[str, dict] = {}
        for leaf in defn.get("parameter_filters") or []:
            if (
                isinstance(leaf, (list, tuple))
                and len(leaf) >= 3
                and isinstance(leaf[2], dict)
                and "param" in leaf[2]
            ):
                param_links[leaf[2]["param"]] = {
                    "filter_field": leaf[0],
                    "filter_op": leaf[1],
                }
        parameters_ui = []
        for p in defn.get("parameters") or []:
            link = param_links.get(p.get("name"), {})
            parameters_ui.append({
                **p,
                "filter_field": link.get("filter_field", ""),
                "filter_op": link.get("filter_op", "ilike"),
            })
        report_mode = (
            "summary"
            if defn.get("groupby") and defn.get("measures")
            else "detail"
        )
        column_sort: dict[str, str] = {}
        order_rules: list[dict] = []
        for item in defn.get("order") or []:
            parts = str(item).strip().rsplit(None, 1)
            if len(parts) != 2:
                continue
            field, direction = parts[0], parts[1].lower()
            if direction not in ("asc", "desc"):
                continue
            column_sort[field] = direction
            order_rules.append({
                "field": field,
                "direction": direction,
                "label": field,
            })
        alpine_cfg = {
            "reportId": report_rec.id,
            "reportMode": report_mode,
            "meta": {
                "name": report_rec.name,
                "description": report_rec.description or "",
                "root_model": report_rec.root_model,
                "row_limit": report_rec.row_limit or 10000,
                "schedule_active": bool(report_rec.schedule_active),
                "output_format": report_rec.output_format or "xlsx",
            },
            "definition": {
                **defn,
                "filters": filters_ui,
                "parameters": parameters_ui,
            },
            "columnSort": column_sort,
            "orderRules": order_rules,
        }
    ctx = layout_context(env, current_path, leaf_label=page_title)
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Reports", "href": "/web/records/reports/report.list"},
        {"label": page_title, "href": None},
    ]
    template = _env.get_template("report_builder.html")
    return template.render(
        page_title=page_title,
        alpine_config=alpine_cfg,
        **ctx,
    )


def render_workflow_transition_form(
    env,
    instance_id: int,
    transition_key: str,
    *,
    errors: dict | None = None,
    form_error: str | None = None,
    values: dict | None = None,
) -> str | None:
    """HTMX fragment for a workflow transition stage form (PvDialog body)."""
    from pyvelm.workflow.engine import WorkflowEngine

    if "workflow.instance" not in env.registry:
        return None
    Instance = env["workflow.instance"]
    inst = Instance.search([("id", "=", instance_id)], limit=1)
    if not inst:
        return None
    inst.ensure_one()
    tr_ui = next(
        (
            t
            for t in WorkflowEngine.available_transitions(env, inst)
            if t.get("key") == transition_key
        ),
        None,
    )
    if tr_ui is None:
        return None
    post_url = f"/web/workflow/instances/{instance_id}/transition/{transition_key}"
    template = _env.get_template("workflow_transition_form.html")
    return template.render(
        transition_label=tr_ui["label"],
        transition_key=transition_key,
        instance_id=instance_id,
        form_fields=tr_ui.get("form_fields") or [],
        post_url=post_url,
        values=values or {},
        errors=errors or {},
        form_error=form_error,
    )


def render_workflow_inbox_page(env, current_path: str | None = None) -> str:
    from pyvelm.workflow.inbox import list_inbox_items

    items = list_inbox_items(env)
    ctx = layout_context(env, current_path, leaf_label="My approvals")
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Workflows", "href": "/web/views/workflow/workflow_definition.list"},
        {"label": "My approvals", "href": None},
    ]
    template = _env.get_template("workflow_inbox.html")
    return template.render(items=items, **ctx)


def render_workflow_builder_page(
    env, workflow_rec=None, current_path: str | None = None,
) -> str:
    """Visual workflow designer — create or edit."""
    import json as _json

    from pyvelm.reports.fields_api import list_readable_models
    from pyvelm.workflow.engine import parse_definition
    from pyvelm.workflow.service import list_groups, list_model_fields, list_users

    page_title = "New workflow"
    alpine_cfg: dict = {
        "workflowId": None,
        "meta": {"name": "", "description": "", "model": "", "active": True},
        "definition": {
            "version": 1,
            "model": "",
            "states": [
                {"key": "draft", "label": "Draft", "initial": True, "_uid": "w1"},
                {"key": "done", "label": "Done", "final": True, "_uid": "w2"},
            ],
            "transitions": [],
        },
        "models": list_readable_models(env),
        "groups": list_groups(env),
        "users": list_users(env),
        "recordFields": [],
    }
    if workflow_rec is not None:
        workflow_rec.ensure_one()
        page_title = workflow_rec.name
        defn = parse_definition(workflow_rec.definition)
        alpine_cfg["workflowId"] = workflow_rec.id
        alpine_cfg["meta"] = {
            "name": workflow_rec.name,
            "description": workflow_rec.description or "",
            "model": workflow_rec.model,
            "active": bool(workflow_rec.active),
        }
        alpine_cfg["definition"] = defn
        if defn.get("auto_start"):
            alpine_cfg["definition"]["auto_start"] = True
        if workflow_rec.model:
            alpine_cfg["recordFields"] = list_model_fields(env, workflow_rec.model)

    ctx = layout_context(env, current_path, leaf_label=page_title)
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Workflows", "href": "/web/views/workflow/workflow_definition.list"},
        {"label": page_title, "href": None},
    ]
    template = _env.get_template("workflow_builder.html")
    return template.render(
        page_title=page_title,
        alpine_config=alpine_cfg,
        **ctx,
    )


STATIC_DIR = Path(__file__).parent / "static"


# ---- shared layout context ----------------------------------------------
#
# Every full-page render (list / form / kanban / admin) extends
# `layouts/main.html`, which expects a stable bundle of "who am I /
# what are my apps / what are my companies" data plus the menu tree.
# `layout_context(env, current_path=None)` produces that bundle so
# individual renderers don't have to re-build it.


def _menu_target_model(env, href: str | None) -> str | None:
    """Model a menu entry lists; see :func:`pyvelm.menu.menu_target_model`."""
    from pyvelm.menu import menu_target_model

    return menu_target_model(env, href)


def _menu_node_visible(env, node: dict) -> bool:
    """Sidebar visibility gate; see :func:`pyvelm.menu.menu_node_visible`."""
    from pyvelm.menu import menu_node_visible

    return menu_node_visible(env, node)


def _menu(env, current_path: str | None) -> list[dict]:
    """Build the navigation menu tree; see :func:`pyvelm.menu.build_menu_tree`."""
    from pyvelm.menu import build_menu_tree

    return build_menu_tree(env, current_path)


def _menu_entry_for_href(
    menu_tree: list, href: str
) -> tuple[dict | None, dict | None]:
    """Return ``(parent, leaf)`` whose ``href`` equals *href*."""
    from pyvelm.menu import find_menu_entry

    return find_menu_entry(menu_tree, href)


def _label_for_href(menu_tree: list, href: str, fallback: str) -> str:
    _parent, leaf = _menu_entry_for_href(menu_tree, href)
    if leaf is not None:
        return leaf.get("label") or fallback
    return fallback


def _view_breadcrumb(
    env,
    module: str,
    name: str,
    menu_tree: list | None = None,
    *,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
    link_query: bool = True,
) -> dict | None:
    """Return ``{label, href}`` for any registered view."""
    ui_view = _load_ui_view(env, module, name)
    if ui_view is None:
        return None
    href = f"/web/views/{module}/{name}"
    if link_query:
        qs = encode_view_nav_query(
            module,
            name,
            search=search,
            order=order,
            filters=filters,
            group_by=group_by,
            page=page,
            page_size=page_size,
            bc_stack=bc_stack,
        )
        if qs:
            href = f"{href}?{qs}"
    from .views import resolve_arch

    fallback = _view_title(ui_view, resolve_arch(ui_view))
    label = _label_for_href(
        menu_tree or [], f"/web/views/{module}/{name}", fallback
    )
    return {"label": label, "href": href}


def _list_breadcrumb_for_model(
    env,
    model_name: str,
    menu_tree: list | None = None,
    *,
    list_module: str | None = None,
    list_name: str | None = None,
    list_search: str = "",
    list_order: str = "",
    list_filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
) -> dict | None:
    """Return ``{label, href}`` for the parent view (list, kanban, …)."""
    ref_view = _load_ref_view(env, list_module, list_name, model_name)
    if ref_view is None:
        return None
    return _view_breadcrumb(
        env,
        ref_view.module,
        ref_view.name,
        menu_tree,
        search=list_search,
        order=list_order,
        filters=list_filters,
        group_by=group_by,
        page=page,
        page_size=page_size,
        bc_stack=bc_stack,
    )


def build_form_breadcrumbs(
    menu_tree: list,
    env,
    *,
    ref_module: str | None = None,
    ref_name: str | None = None,
    bc_stack: list[tuple[str, str]] | None = None,
    search: str = "",
    order: str = "",
    filters: str = "",
    group_by: str = "",
    page: int | None = None,
    page_size: int | None = None,
    leaf_label: str | None = None,
) -> list[dict]:
    """Odoo-style trail: Home → …ancestors… → parent view → optional record."""
    from pyvelm.home import home_url

    crumbs: list[dict] = [{"label": "Home", "href": home_url()}]
    for mod, view_name in bc_stack or []:
        entry = _view_breadcrumb(
            env, mod, view_name, menu_tree, link_query=False
        )
        if entry:
            crumbs.append(entry)
    if ref_module and ref_name:
        parent = _view_breadcrumb(
            env,
            ref_module,
            ref_name,
            menu_tree,
            search=search,
            order=order,
            filters=filters,
            group_by=group_by,
            page=page,
            page_size=page_size,
            bc_stack=bc_stack,
        )
        if parent:
            crumbs.append(parent)
    if leaf_label:
        crumbs.append({"label": leaf_label, "href": None})
    return crumbs


def build_breadcrumbs(
    menu_tree: list,
    current_path: str | None,
    leaf_label: str | None = None,
    *,
    parent_href: str | None = None,
    parent_label: str | None = None,
) -> list[dict]:
    """Build navigation crumbs: Home → list → record/detail.

    * Home links to :func:`~pyvelm.home.home_url` (``PYVELM_HOME_URL``).
    * List / kanban / graph pages get a single leaf (the view), linked
      from Home only on the leaf when it is not the current page.
    * Form / new / edit pages pass ``parent_href`` + ``parent_label``
      (the model's list view) so the middle crumb links back to the
      list. The record title stays in the page heading only (no third
      crumb unless ``leaf_label`` is passed explicitly).
    """
    from pyvelm.home import home_url

    crumbs: list[dict] = [{"label": "Home", "href": home_url()}]
    if parent_href and parent_label:
        crumbs.append({"label": parent_label, "href": parent_href})
        if leaf_label:
            crumbs.append({"label": leaf_label, "href": None})
        return crumbs

    _parent, leaf = (
        _menu_entry_for_href(menu_tree, current_path)
        if current_path
        else (None, None)
    )
    if leaf is not None:
        crumbs.append({"label": leaf_label or leaf.get("label") or "Page", "href": None})
    elif leaf_label:
        crumbs.append({"label": leaf_label, "href": None})
    return crumbs


def layout_context(
    env,
    current_path: str | None = None,
    leaf_label: str | None = None,
    *,
    breadcrumbs: list | None = None,
) -> dict:
    """Return the shell context every page renderer passes to the
    `layouts/main.html` base template."""
    name = ""
    login = ""
    initial = "?"
    avatar_url = ""
    if env.uid is not None and "res.users" in env.registry:
        env.prime_current_user_cache()
        user = env["res.users"].browse(env.uid)
        if env["res.users"].search([("id", "=", env.uid)], limit=1):
            name = user.name or user.login or f"user#{user.id}"
            login = user.login or ""
            initial = (name[:1] or "?").upper()
            if "avatar_url" in env["res.users"]._fields:
                avatar_url = user.avatar_url or ""

    companies: list[dict] = []
    current_company_name = ""
    if "res.company" in env.registry:
        for c in env.with_company(None).sudo()["res.company"].search([]):
            companies.append({"id": c.id, "name": c.name})
            if env.company_id == c.id:
                current_company_name = c.name

    from pyvelm.branding import branding_context

    from pyvelm.home import home_url

    from pyvelm.menu import (
        build_menu_tree,
        menu_active_path_from_breadcrumbs,
        menu_layout_context,
    )

    home_href = home_url()
    if breadcrumbs is None:
        prelim_menu = build_menu_tree(env, current_path)
        breadcrumbs = build_breadcrumbs(prelim_menu, current_path, leaf_label)
    menu_path = menu_active_path_from_breadcrumbs(
        breadcrumbs,
        current_path=current_path,
        home_href=home_href,
    )
    menu_tree = build_menu_tree(env, menu_path)
    return {
        **menu_layout_context(menu_tree, menu_path),
        "home_href": home_href,
        "current_user_name": name,
        "current_user_login": login,
        "current_user_initial": initial,
        "current_user_avatar": avatar_url,
        "companies": companies,
        "current_company_id": env.company_id,
        "current_company_name": current_company_name,
        **branding_context(env),
        # Default crumbs derived from the menu. Pages that want a
        # different leaf label (e.g. the record name on a form view)
        # pass `leaf_label`; renderers can override `breadcrumbs`
        # directly when the page lives outside the menu altogether.
        "breadcrumbs": breadcrumbs,
    }
