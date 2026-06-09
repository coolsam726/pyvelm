"""admin module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("admin")
    .version(0, 1, 0)
    .summary("Settings, Security, and Workflows UI for the base models.")
    .category("System")
    .author("pyvelm")
    .depends("base")
    .data(
        "views/acl.py",
        "views/dashboard.py",
        "views/menu.py",
    )
    .install_hook("admin.hooks:install")
    .catalog_access("res.users", "read", policy="view_any")
)
