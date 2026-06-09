"""partners_pro: model extension + view-patch module.

Demonstrates Stage 7 _inherit: adds `vip_note` to res.partner and
overrides `_compute_display_name` to prefix VIP partners with ★.
Also patches the `partners.partner.list` view (view inheritance
from Stage 4 is unchanged).
"""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("partners_pro")
    .version(0, 1, 0)
    .summary("VIP markers and richer display logic for partners.")
    .category("Business")
    .author("pyvelm")
    .depends("partners")
    .data("views/partner.py")
    .install_hook("partners_pro.hooks:install")
)
