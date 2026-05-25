"""Tests for Flowbite date/time form widgets and parsing."""

from datetime import date, datetime

from pyvelm.fields import Date, Datetime, Time
from pyvelm.render import _parse_datetime_field, parse_form_vals
from pyvelm.widgets.datetime_pickers import (
    combine_datetime_form_values,
    render_date_picker,
    render_datetime_picker,
)


class _Form(dict):
    def getlist(self, key):
        v = self.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


def test_render_date_picker_has_flowbite_attrs():
    html = str(
        render_date_picker(date(2026, 4, 17), {"name": "due_on"}, Date())
    )
    assert "datepicker" in html
    assert 'datepicker-format="yyyy-mm-dd"' in html
    assert "datepicker-autohide" in html
    assert 'name="due_on"' in html
    assert 'value="2026-04-17"' in html


def test_render_datetime_picker_unified_popup():
    html = str(
        render_datetime_picker(
            datetime(2026, 4, 17, 14, 30),
            {"name": "starts_at"},
            Datetime(),
            env=None,
        )
    )
    assert 'name="starts_at"' in html
    assert 'type="hidden"' in html
    assert 'value="2026-04-17T14:30"' in html
    assert "data-pv-datetime-picker" in html
    assert "data-pv-datetime-trigger" in html
    assert "data-pv-datetime-inline" in html
    assert "inline-datepicker" not in html
    assert "data-datepicker-format" in html
    assert "pv-datetime-panel" in html
    assert 'data-date="2026-04-17"' in html
    assert 'data-pv-datetime-time' in html
    assert 'value="14:30"' in html
    assert "starts_at_date" not in html
    assert "datetime-local" not in html


def test_combine_datetime_form_values_single():
    form = _Form({"evt": "2026-05-01T09:15"})
    combined, err = combine_datetime_form_values(form, "evt", env=None)
    assert err is None
    assert combined == "2026-05-01T09:15"


def test_combine_datetime_form_values_legacy_split():
    form = _Form({"evt_date": "2026-05-01", "evt_time": "09:15"})
    combined, err = combine_datetime_form_values(form, "evt", env=None)
    assert err is None
    assert combined == "2026-05-01T09:15"


def test_parse_datetime_field_single():
    form = _Form({"starts_at": "2026-05-01T10:00"})
    value, err = _parse_datetime_field(form, "starts_at", Datetime(), env=None)
    assert err is None
    assert value == datetime(2026, 5, 1, 10, 0)


class _Model:
    _name = "test.picker"
    _fields = {
        "due_on": Date(),
        "starts_at": Datetime(),
        "opens_at": Time(),
    }


def test_parse_form_vals_datetime_single():
    form = _Form(
        {
            "due_on": "2026-06-01",
            "starts_at": "2026-06-02T08:30",
            "opens_at": "07:45",
        }
    )
    vals, errors = parse_form_vals(_Model, form, env=None)
    assert not errors
    assert vals["due_on"] == date(2026, 6, 1)
    assert vals["starts_at"] == datetime(2026, 6, 2, 8, 30)
    assert str(vals["opens_at"]) == "07:45:00" or vals["opens_at"].hour == 7
