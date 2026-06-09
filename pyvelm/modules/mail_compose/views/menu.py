"""Menu entry for the composer drafts list."""

from pyvelm.builders import Menus, ViewsData

m = Menus("mail_compose")

views_data = (
    ViewsData.make()
    .menus(
        m.item(
            "workflows.mail_compose",
            "Compose drafts",
            parent=("admin", "workflows.messaging"),
            view="mail_compose.list",
            sequence=30,
            policy="view_any",
        ),
    )
)
