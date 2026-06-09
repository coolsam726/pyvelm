"""file_manager module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("file_manager")
    .version(0, 3, 0)
    .summary(
        "Drive-style file library + folder tree + bulk actions + file-picker "
        "widget over ir.attachment."
    )
    .category("System")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/file.py",
        "views/folder.py",
        "views/menu.py",
    )
    .install_hook("file_manager.hooks:install")
)
