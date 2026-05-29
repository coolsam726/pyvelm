"""Extra coverage for ``pyvelm.widgets.datetime_pickers``."""
from __future__ import annotations

import unittest
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from pyvelm.fields import Date, Datetime, Time
from pyvelm.widgets import datetime_pickers as dp
from pyvelm.widgets.datetime_pickers import (
    combine_datetime_form_values,
    render_date_picker,
    render_datetime_picker,
    render_time_picker,
)


class _Form(dict):
    def getlist(self, key):
        v = self.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


class FormatValueTests(unittest.TestCase):
    def test_format_date_value_variants(self):
        self.assertEqual(dp._format_date_value(None), "")
        self.assertEqual(
            dp._format_date_value(datetime(2026, 1, 2, 3, 4)),
            "2026-01-02",
        )
        self.assertEqual(dp._format_date_value(date(2026, 1, 2)), "2026-01-02")

    def test_format_date_value_isoformat_fallback(self):
        class _D:
            def isoformat(self):
                return "2026-03-01"

        self.assertEqual(dp._format_date_value(_D()), "2026-03-01")
        self.assertEqual(dp._format_date_value(99), "99")

    def test_format_time_value(self):
        self.assertEqual(dp._format_time_value(None), "")
        self.assertEqual(
            dp._format_time_value(datetime(2026, 1, 1, 14, 5)),
            "14:05",
        )
        self.assertEqual(dp._format_time_value(time(9, 30)), "09:30")
        self.assertEqual(dp._format_time_value("raw"), "raw")

    def test_datetime_parts_empty(self):
        self.assertEqual(dp._datetime_parts(None, None), ("", "", "00:00"))

    def test_format_datetime_local_without_strftime(self):
        self.assertEqual(dp._format_datetime_local_value("text", None), "text")

    def test_format_datetime_local_with_utc_to_local(self):
        env = MagicMock()
        value = datetime(2026, 6, 1, 12, 0)
        with patch("pyvelm.render._utc_to_local", return_value=value):
            out = dp._format_datetime_local_value(value, env)
        self.assertEqual(out, "2026-06-01T12:00")


class RenderPickerTests(unittest.TestCase):
    def test_date_picker_readonly_skips_datepicker_attrs(self):
        html = str(
            render_date_picker(
                date(2026, 4, 1),
                {"name": "d", "readonly": True},
                Date(required=True),
            )
        )
        self.assertNotIn("datepicker-autohide", html)
        self.assertIn("disabled", html)
        self.assertIn("required", html)

    def test_time_picker_renders_native_input(self):
        html = str(
            render_time_picker(
                time(8, 15),
                {"name": "opens"},
                Time(),
            )
        )
        self.assertIn('type="time"', html)
        self.assertIn('value="08:15"', html)
        self.assertIn("data-pv-timepicker", html)

    def test_datetime_picker_readonly_with_value(self):
        html = str(
            render_datetime_picker(
                datetime(2026, 5, 1, 10, 0),
                {"name": "evt", "readonly": True},
                Datetime(),
                env=None,
            )
        )
        self.assertIn("2026-05-01 10:00", html)
        self.assertIn('type="hidden"', html)
        self.assertNotIn("data-pv-datetime-trigger", html)

    def test_datetime_picker_readonly_empty_shows_dash(self):
        html = str(
            render_datetime_picker(
                None,
                {"name": "evt", "readonly": True},
                Datetime(),
                env=None,
            )
        )
        self.assertIn("—</div>", html)


class CombineDatetimeFormTests(unittest.TestCase):
    def test_space_separator_normalized(self):
        form = _Form({"evt": "2026-05-01 09:15"})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertIsNone(err)
        self.assertEqual(combined, "2026-05-01T09:15")

    def test_empty_single_field_clears(self):
        form = _Form({"evt": ""})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertIsNone(combined)
        self.assertIsNone(err)

    def test_date_only_legacy(self):
        form = _Form({"evt_date": "2026-05-01", "evt_time": ""})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertIsNone(err)
        self.assertEqual(combined, "2026-05-01T00:00")

    def test_partial_legacy_returns_error(self):
        form = _Form({"evt_time": "09:00"})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertIsNone(combined)
        self.assertIn("both date and time", err or "")

    def test_getlist_uses_last_value(self):
        form = _Form({"evt": ["2026-01-01T00:00", "2026-01-02T00:00"]})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertEqual(combined, "2026-01-02T00:00")
        self.assertIsNone(err)

    def test_datepicker_attrs_readonly(self):
        self.assertEqual(dp._datepicker_attrs(readonly=True), "")
        self.assertIn("datepicker", dp._datepicker_attrs(readonly=False))

    def test_legacy_missing_keys_both_empty(self):
        form = _Form({})
        combined, err = combine_datetime_form_values(form, "evt", env=None)
        self.assertIsNone(combined)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
