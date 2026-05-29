"""A field widget that opens the Layout Designer in PvDialog."""

from markupsafe import Markup
from pyvelm import Char
from pyvelm.render import widget

_BUTTON = (
    '<button type="button" '
    'class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium '
    'text-white rounded-md bg-fg-brand hover:opacity-90 transition" '
    'data-pv-dialog data-pv-dialog-url="/report/layout/designer?company_id={cid}" '
    'data-pv-dialog-title="Design Document Layout">'
    '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" '
    'stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" '
    'd="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 '
    '008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m'
    '-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 '
    '004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 '
    '15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg>'
    'Design layout</button>'
)


def _render_design_button(value, spec, field):  # noqa: ANN001
    rec = spec.get("_record")
    cid = rec.id if rec is not None and rec else 0
    return Markup(_BUTTON.format(cid=cid))


widget(Char, hint="design_button")(_render_design_button)
widget(Char, hint="design_button", mode="edit")(_render_design_button)
