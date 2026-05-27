"""Sidebar entries for the technical module.

The whole subtree is ``dev_only=True``: it never renders unless
``PYVELM_ENV=development``. Within development, the entries also
require admin write on each underlying model (granted by the install
hook), so non-admin developers still don't see the editors.
"""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("technical")

MENUS: list[Menu] = [
    m.group(
        "technical",
        "Technical",
        icon="wrench-screwdriver",
        sequence=900,  # tail-end of the app rail
        dev_only=True,
    ),
    m.group(
        "technical.ui",
        "User Interface",
        parent="technical",
        sequence=10,
        dev_only=True,
    ),
    m.item(
        "technical.ui.menus",
        "Menu entries",
        parent="technical.ui",
        view="technical.menu.list",
        perm="write",
        model="ir.ui.menu",
        sequence=10,
        dev_only=True,
    ),
    m.item(
        "technical.ui.views",
        "Views",
        parent="technical.ui",
        view="technical.view.list",
        perm="write",
        model="ir.ui.view",
        sequence=20,
        dev_only=True,
    ),
    m.group(
        "technical.data",
        "Data",
        parent="technical",
        sequence=20,
        dev_only=True,
    ),
    m.item(
        "technical.data.attachments",
        "Attachments",
        parent="technical.data",
        view="technical.attachment.list",
        perm="write",
        model="ir.attachment",
        sequence=10,
        dev_only=True,
    ),
]
