"""contacts module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("contacts")
    .version(0, 1, 0)
    .display_name("Contacts")
    .summary("Companies, contacts, and the partner directory.")
    .category("Business")
    .author("pyvelm")
    .depends("base")
    .data(
        "views/partner.py",
        "views/menu.py",
    )
    .install_hook("contacts.hooks:install")
    .sync_hook("contacts.hooks:sync")
)
