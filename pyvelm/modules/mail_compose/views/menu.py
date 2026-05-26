"""Menu entry for the composer drafts list."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("mail_compose")

MENUS: list[Menu] = [
    m.item(
        "workflows.mail_compose",
        "Compose drafts",
        # The Workflows group is owned by the admin module — point at it
        # with the (module, name) tuple so the menu loader resolves to
        # ``admin.workflows`` instead of ``mail_compose.workflows``.
        parent=("admin", "workflows"),
        view="mail_compose.list",
        sequence=45,
        policy="view_any",
    ),
]
