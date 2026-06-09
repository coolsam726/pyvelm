"""Sidebar: Vellum demo (installed with examples/serve.py)."""

from pyvelm.builders import Menus, ViewsData

m = Menus("vellum_demo")

views_data = (
    ViewsData.make()
    .menus(
        m.group("vellum_demo", "Vellum demo", icon="document-text", sequence=45).children(
            [
                m.group("vellum_demo.records", "Records", sequence=10).children(
                    [
                        m.item(
                            "vellum_demo.notes",
                            "Demo notes",
                            view="demo_note.list",
                            sequence=10,
                        ),
                        m.item(
                            "vellum_demo.comments",
                            "Comments",
                            view="demo_comment.list",
                            sequence=20,
                        ),
                        m.item(
                            "vellum_demo.soft_notes",
                            "Soft notes",
                            view="demo_soft_note.list",
                            sequence=30,
                        ),
                    ]
                ),
            ]
        ),
    )
)
