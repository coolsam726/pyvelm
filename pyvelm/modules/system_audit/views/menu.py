"""Security → Audit menu entries."""

from pyvelm.builders import Menus, ViewsData

m = Menus("system_audit")

views_data = (
    ViewsData.make()
    .menus(
        m.group("audit", "Audit", parent=("admin", "security"), sequence=30).children(
            [
                m.item(
                    "audit.log",
                    "Audit log",
                    view="audit_log.list",
                    sequence=10,
                    policy="view_any",
                ),
                m.item(
                    "audit.logins",
                    "Login history",
                    view="login_log.list",
                    sequence=20,
                    policy="view_any",
                ),
                m.item(
                    "audit.lifecycle",
                    "User lifecycle",
                    view="user_lifecycle.list",
                    sequence=30,
                    policy="view_any",
                ),
            ]
        ),
    )
)
