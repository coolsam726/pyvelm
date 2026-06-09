"""base module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("base")
    .version(0, 33, 0)
    .summary("Core models and framework primitives.")
    .category("System")
    .author("pyvelm")
    .data("views/menu.py")
    # Seed default Admin group + uid=1 superuser on first install so the
    # loader has a sane authenticated identity to run as. See base/hooks.py.
    .install_hook("base.hooks:install")
    .sync_hook("base.hooks:sync")
    .web_routes("base.web:register_routes")
)
