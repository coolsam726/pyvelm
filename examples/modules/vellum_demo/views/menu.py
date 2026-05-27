"""Sidebar: Vellum demo (installed with examples/serve.py)."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("vellum_demo")

MENUS: list[Menu] = [
    m.group("vellum_demo", "Vellum demo", icon="document-text", sequence=45),
    m.group("vellum_demo.records", "Records", parent="vellum_demo", sequence=10),
    m.item(
        "vellum_demo.notes",
        "Demo notes",
        parent="vellum_demo.records",
        view="demo_note.list",
        sequence=10,
    ),
    m.item(
        "vellum_demo.comments",
        "Comments",
        parent="vellum_demo.records",
        view="demo_comment.list",
        sequence=20,
    ),
    m.item(
        "vellum_demo.soft_notes",
        "Soft notes",
        parent="vellum_demo.records",
        view="demo_soft_note.list",
        sequence=30,
    ),
]
