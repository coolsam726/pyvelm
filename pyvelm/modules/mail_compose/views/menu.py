"""Menu entry for the composer drafts list."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("mail_compose")

MENUS: list[Menu] = [
    m.item(
        "workflows.mail_compose",
        "Compose drafts",
        parent=("admin", "workflows.messaging"),
        view="mail_compose.list",
        sequence=30,
        policy="view_any",
    ),
]
