"""workflow module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("workflow")
    .version(0, 2, 0)
    .display_name("Workflows")
    .summary(
        "Visual approval and task workflows — state machines, stage forms, "
        "and multi-step sign-off on any model."
    )
    .category("System")
    .author("pyvelm")
    .depends("base", "admin")
    .data(
        "views/definition.py",
        "views/runtime.py",
        "views/menu.py",
    )
    .install_hook("workflow.hooks:install")
    .sync_hook("workflow.hooks:sync")
)
