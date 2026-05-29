"""res.company — the company/tenant model.

Each record represents an independent company. Users and partners carry
a Many2one to their "home" company; the Environment's company_id scopes
searches automatically when set.

Note: company_id is added directly to res.users in security.py (same
module) and to res.partner in the partners module (which depends on base
and thus loads res.company first).
"""
from __future__ import annotations

from pyvelm import BaseModel, Boolean, Char, Many2one

from ..constants import MENU_LAYOUT_CHOICES


class Company(BaseModel):
    _name = "res.company"

    name = Char(required=True)
    active = Boolean(default=True)
    # Each company has a "home" currency. Monetary fields (slice C)
    # default to their record's company's currency. ON DELETE SET NULL
    # so deleting a currency doesn't cascade-delete the company.
    currency_id = Many2one("res.currency", ondelete="SET NULL")
    # IANA timezone name (e.g. "Africa/Nairobi", "Europe/Paris").
    # Datetime widgets render the active company's tz on display and
    # parse user input as that tz before converting to naive UTC for
    # storage. ``UTC`` is the safe default; no validation here — the
    # render layer falls back to UTC if the value can't be resolved.
    timezone = Char(default="UTC", string="Timezone")
    # Hex accent for this company (e.g. ``#6366f1``). When the user has
    # this company active, the UI overrides the default primary palette.
    # Empty → framework default (indigo in tailwind.css).
    primary_color = Char(string="Primary color")

    # White-label chrome (sidebar, login, footer). Empty fields fall back to
    # ``PYVELM_*`` environment variables — see ``pyvelm.branding``.
    app_name = Char(string="Application name")
    app_tagline = Char(string="Tagline")
    logo_url = Char(string="Logo URL (light)")
    logo_url_dark = Char(string="Logo URL (dark)")
    favicon_url = Char(string="Favicon URL")
    copyright_text = Char(string="Copyright")
    support_email = Char(string="Support email")
    support_url = Char(string="Support URL")
    show_powered_by = Boolean(default=True, string="Show powered by pyvelm")
    menu_layout = Char(
        default="",
        string="Navigation Layout",
        choices=MENU_LAYOUT_CHOICES,
    )
