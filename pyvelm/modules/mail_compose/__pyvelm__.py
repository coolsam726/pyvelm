"""mail_compose module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("mail_compose")
    .version(0, 1, 1)
    .summary(
        "Rich email composer with templates, multi-recipient, Cc/Bcc, and attachments."
    )
    .category("Workflows")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/compose.py",
        "views/menu.py",
    )
    .install_hook("mail_compose.hooks:install")
)
