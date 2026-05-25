"""Per-field dialog vs inline UX for O2m/M2m on forms."""
from __future__ import annotations

import unittest

from pyvelm.render import (
    _m2m_use_dialog_editor,
    _o2m_show_table,
    _o2m_use_inline_edit,
    _relational_widget,
)


class RelationalWidgetModeTests(unittest.TestCase):
    def test_table_alias_is_inline(self):
        self.assertEqual(_relational_widget({"widget": "table"}), "inline")

    def test_o2m_default_dialog_when_form_view(self):
        spec = {"_form_view_url": "/web/views/partners/partner.form"}
        self.assertFalse(_o2m_use_inline_edit(spec))
        self.assertTrue(_o2m_show_table(spec))

    def test_o2m_inline_explicit(self):
        spec = {
            "widget": "inline",
            "_form_view_url": "/web/views/x/form",
            "_list_view_url": "/web/views/x/list",
        }
        self.assertTrue(_o2m_use_inline_edit(spec))
        self.assertTrue(_o2m_show_table(spec))

    def test_o2m_no_form_falls_back_to_chips(self):
        spec = {"_list_view_url": "/web/views/x/list"}
        self.assertFalse(_o2m_use_inline_edit(spec))
        self.assertFalse(_o2m_show_table(spec))

    def test_m2m_default_dialog_when_form_view(self):
        spec = {"_form_view_url": "/web/views/partners/tag.form"}
        self.assertTrue(_m2m_use_dialog_editor(spec))

    def test_m2m_inline_opt_out(self):
        spec = {
            "widget": "inline",
            "_form_view_url": "/web/views/partners/tag.form",
        }
        self.assertFalse(_m2m_use_dialog_editor(spec))

