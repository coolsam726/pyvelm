"""partners module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("partners")
    .version(0, 4, 0)
    .summary("Companies, contacts, and the partner directory.")
    .category("Business")
    .author("pyvelm")
    .depends("base")
    .data(
        "views/partner.py",
        "views/menu.py",
    )
    .install_hook("partners.hooks:install")
    .sync_hook("partners.hooks:sync")
)
