"""partners_pro: model extension + view-patch module.

Demonstrates Stage 7 _inherit: adds `vip_note` to res.partner and
overrides `_compute_display_name` to prefix VIP partners with ★.
Also patches the `partners.partner.list` view (view inheritance
from Stage 4 is unchanged).
"""
NAME: str = "partners_pro"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "VIP markers and richer display logic for partners."
CATEGORY: str = "Business"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["partners"]
DATA: list[str] = [
    "views/partner.py",
]
INSTALL_HOOK: str = "partners_pro.hooks:install"
