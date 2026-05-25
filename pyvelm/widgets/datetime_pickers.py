"""Flowbite datepicker widgets for pyvelm form fields (see nuru datepicker templates)."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from markupsafe import Markup, escape

from pyvelm.fields import Date, Datetime, Field, Time

# Storage / submission format (ISO dates; matches Flowbite datepicker-format).
_DATE_FORMAT = "yyyy-mm-dd"

_CALENDAR_ICON = (
    '<svg class="w-4 h-4 text-body-subtle" aria-hidden="true" '
    'xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 20 20">'
    '<path d="M20 4a2 2 0 0 0-2-2h-2V1a1 1 0 0 0-2 0v1h-3V1a1 1 0 0 0-2 0v1H6V1a1 1 0 0 0-2 0v1H2a2 2 0 0 0-2 2v2h20V4ZM0 18a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8H0v10Zm5-8h10a1 1 0 0 1 0 2H5a1 1 0 0 1 0-2Z"/>'
    "</svg>"
)

_CLOCK_ICON = (
    '<svg class="w-4 h-4 text-body-subtle" aria-hidden="true" '
    'xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">'
    '<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" '
    'stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>'
    "</svg>"
)

_INPUT_CLS = (
    "block w-full px-2.5 py-2 text-sm rounded-lg "
    "bg-neutral-primary border border-default text-heading "
    "placeholder:text-body-subtle "
    "focus:outline-none focus:ring-2 focus:ring-fg-brand focus:border-fg-brand "
    "disabled:cursor-not-allowed disabled:opacity-60"
)


def _readonly_marker(spec: dict) -> str:
    return " disabled" if spec.get("readonly") else ""


def _required_marker(field: Field) -> str:
    return " required" if getattr(field, "required", False) else ""


def _input_cls(spec: dict, field: Field, *, extra: str = "") -> str:
    return f"{_INPUT_CLS}{extra}{_readonly_marker(spec)}{_required_marker(field)}"


def _format_date_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _format_datetime_local_value(value: Any, env) -> str:
    """ISO value for hidden submit + popup (minute precision, local tz)."""
    if value is None:
        return ""
    if not hasattr(value, "strftime"):
        return str(value)
    from pyvelm.render import _utc_to_local

    local = _utc_to_local(value, env) or value
    return local.strftime("%Y-%m-%dT%H:%M")


def _datetime_parts(value: Any, env) -> tuple[str, str, str]:
    """Return ``(hidden_iso, date_yyyy_mm_dd, time_hh_mm)`` for the popup."""
    iso = _format_datetime_local_value(value, env)
    if not iso:
        return "", "", "00:00"
    norm = iso.replace(" ", "T")
    date_part, _, time_part = norm.partition("T")
    return iso, date_part, (time_part[:5] if time_part else "00:00")


def _format_time_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def _datepicker_attrs(*, readonly: bool) -> str:
    if readonly:
        return ""
    return (
        f' datepicker datepicker-format="{_DATE_FORMAT}"'
        " datepicker-autohide datepicker-buttons"
    )


def render_date_picker(value: Any, spec: dict, field: Date) -> Markup:
    """Single-date Flowbite picker (text input + calendar popup)."""
    name = escape(spec["name"])
    val = escape(_format_date_value(value))
    readonly = bool(spec.get("readonly"))
    attrs = _datepicker_attrs(readonly=readonly)
    return Markup(
        f'<div class="relative" data-pv-datepicker>'
        f'<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none z-10">'
        f"{_CALENDAR_ICON}</div>"
        f'<input type="text" name="{name}" value="{val}"{attrs} '
        f'autocomplete="off" class="{_input_cls(spec, field, extra=" ps-9")}">'
        f"</div>"
    )


def render_datetime_picker(
    value: Any, spec: dict, field: Datetime, *, env
) -> Markup:
    """Unified datetime popup: Flowbite inline calendar + time in one panel."""
    name = escape(spec["name"])
    hidden_iso, date_part, time_part = _datetime_parts(value, env)
    hidden_val = escape(hidden_iso)
    date_attr = escape(date_part) if date_part else ""
    time_val = escape(time_part)
    readonly = bool(spec.get("readonly"))
    required = _required_marker(field)
    display = f"{date_part} {time_part}" if hidden_iso else ""
    display_esc = escape(display)
    placeholder = "Select date and time"
    trigger_cls = _input_cls(spec, field, extra=" ps-9 pe-9 text-left cursor-pointer")
    time_cls = (
        "pv-datetime-time-input block flex-1 min-w-0 px-2 py-1.5 text-sm rounded-md "
        "bg-neutral-primary border border-default text-heading "
        "focus:outline-none focus:ring-2 focus:ring-fg-brand focus:border-fg-brand"
    )

    if readonly:
        if display:
            body = (
                f'<div class="px-2.5 py-2 ps-9 text-sm text-heading">{display_esc}</div>'
            )
        else:
            body = '<div class="px-2.5 py-2 ps-9 text-sm text-body-subtle">—</div>'
        return Markup(
            f'<div class="relative" data-pv-datetime-picker>'
            f'<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none z-10">'
            f"{_CALENDAR_ICON}</div>"
            f"{body}"
            f'<input type="hidden" name="{name}" value="{hidden_val}">'
            f"</div>"
        )

    data_date = f' data-date="{date_attr}"' if date_attr else ""
    return Markup(
        f'<div class="relative" data-pv-datetime-picker '
        f'data-pv-datetime-placeholder="{placeholder}">'
        f'<input type="hidden" name="{name}" value="{hidden_val}"{required} '
        f'data-pv-datetime-value>'
        f'<button type="button" data-pv-datetime-trigger '
        f'aria-haspopup="dialog" aria-expanded="false" '
        f'class="{trigger_cls}">'
        f'<span data-pv-datetime-display class="block truncate '
        f'{"text-body-subtle" if not display else ""}">'
        f'{display_esc if display else placeholder}</span>'
        f"</button>"
        f'<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none z-10">'
        f"{_CALENDAR_ICON}</div>"
        f'<div class="absolute inset-y-0 end-0 flex items-center pe-3 pointer-events-none z-10">'
        f"{_CLOCK_ICON}</div>"
        f'<div class="hidden min-w-[17rem] rounded-lg '
        f'border border-default bg-neutral-primary shadow-lg overflow-hidden '
        f'pv-datetime-panel" '
        f'data-pv-datetime-panel role="dialog" aria-label="Pick date and time">'
        f'<div class="pv-datetime-calendar" data-pv-datetime-inline '
        f'data-datepicker-format="{_DATE_FORMAT}"{data_date}></div>'
        f'<div class="pv-datetime-footer">'
        f'<div class="pv-datetime-time-row">'
        f'<span class="text-sm font-medium text-body-subtle shrink-0">Time</span>'
        f'<input type="time" data-pv-datetime-time value="{time_val}" '
        f'class="{time_cls}">'
        f"</div>"
        f'<div class="pv-datetime-actions">'
        f'<button type="button" data-pv-datetime-clear '
        f'class="px-2 py-1 text-sm text-body-subtle hover:text-heading rounded-md '
        f'hover:bg-neutral-secondary transition">Clear</button>'
        f'<button type="button" data-pv-datetime-apply '
        f'class="px-3 py-1.5 text-sm font-medium text-white rounded-md bg-fg-brand '
        f'hover:opacity-90 transition">Done</button>'
        f"</div>"
        f"</div>"
        f"</div>"
        f"</div>"
    )


def render_time_picker(value: Any, spec: dict, field: Time) -> Markup:
    """Styled native time input (nuru TimePicker pattern)."""
    name = escape(spec["name"])
    val = escape(_format_time_value(value))
    return Markup(
        f'<div class="relative" data-pv-timepicker>'
        f'<div class="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none z-10">'
        f"{_CLOCK_ICON}</div>"
        f'<input type="time" name="{name}" value="{val}" '
        f'class="{_input_cls(spec, field, extra=" ps-9")}">'
        f"</div>"
    )


def combine_datetime_form_values(
    form_data, fname: str, *, env
) -> tuple[str | None, str | None]:
    """Parse a datetime from posted form data.

    Prefer a single ``fname`` value (``datetime-local`` or ISO text). Falls back
    to legacy ``{fname}_date`` + ``{fname}_time`` split fields if present.
    """
    if fname in form_data:
        raw = form_data[fname]
        if hasattr(form_data, "getlist"):
            seq = form_data.getlist(fname)
            raw = seq[-1] if seq else ""
        text = "" if raw in (None, "") else str(raw).strip()
        if text:
            return text.replace(" ", "T") if " " in text and "T" not in text else text, None
        if text == "":
            return None, None

    date_key = f"{fname}_date"
    time_key = f"{fname}_time"

    def _get(key: str) -> str:
        if key not in form_data:
            return ""
        if hasattr(form_data, "getlist"):
            seq = form_data.getlist(key)
            return (seq[-1] if seq else "") or ""
        raw = form_data[key]
        return "" if raw in (None, "") else str(raw)

    date_val = _get(date_key).strip()
    time_val = _get(time_key).strip()

    if not date_val and not time_val:
        return None, None
    if date_val and time_val:
        return f"{date_val}T{time_val}", None
    if date_val:
        return f"{date_val}T00:00", None
    return None, "Enter both date and time, or leave both empty."
