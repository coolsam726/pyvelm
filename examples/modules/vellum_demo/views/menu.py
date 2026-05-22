"""Sidebar: Vellum demo (installed with examples/serve.py)."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

_ICON = (
    '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 '
    '6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 '
    '00-6 2.292m0-14.25v14.25"/></svg>'
)

m = Menus("vellum_demo")

MENUS: list[Menu] = [
    m.group("vellum_demo", "Vellum demo", icon=_ICON, sequence=45),
    m.item(
        "vellum_demo.notes",
        "Demo notes",
        parent="vellum_demo",
        view="demo_note.list",
        sequence=10,
    ),
    m.item(
        "vellum_demo.comments",
        "Comments",
        parent="vellum_demo",
        view="demo_comment.list",
        sequence=20,
    ),
    m.item(
        "vellum_demo.soft_notes",
        "Soft notes",
        parent="vellum_demo",
        view="demo_soft_note.list",
        sequence=30,
    ),
]
