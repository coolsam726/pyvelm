"""crm module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("crm")
    .version(0, 1, 0)
    .summary("Sales pipeline, leads, and opportunity tracking.")
    .category("Business")
    .author("pyvelm")
    .depends("base", "partners")
    .data(
        "views/lead.py",
        "views/menu.py",
    )
    .install_hook("crm.hooks:install")
)
