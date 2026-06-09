"""vellum_demo module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("vellum_demo")
    .version(0, 5, 3)
    .display_name("Vellum Demo")
    .summary("Example models exercising the Vellum query builder.")
    .category("Demo")
    .author("pyvelm")
    .depends("base", "vellum")
    .data(
        "views/note.py",
        "views/menu.py",
        "views/comment.py",
    )
    .install_hook("vellum_demo.hooks:install")
    .sync_hook("vellum_demo.hooks:sync")
)
