"""reports module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("reports")
    .version(0, 2, 0)
    .display_name("Report Builder")
    .summary("User-defined reports with secure SQL compilation and Excel export.")
    .category("System")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/report.py",
        "views/menu.py",
    )
    .install_hook("reports.hooks:install")
)
