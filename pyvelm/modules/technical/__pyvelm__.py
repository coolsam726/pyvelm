"""technical module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("technical")
    .version(0, 1, 0)
    .summary(
        "Developer-only editors for low-level records "
        "(ir.ui.menu, ir.ui.view, ir.attachment)."
    )
    .category("System")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/technical.py",
        "views/menu.py",
    )
    .install_hook("technical.hooks:install")
    # Hide the module from the Apps catalog for non-admin users.
    .catalog_access("res.users", "write")
)
