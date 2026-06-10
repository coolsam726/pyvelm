"""system_audit module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("system_audit")
    .version(0, 1, 0)
    .display_name("System Audit")
    .summary(
        "IT audit trail — CRUD events, login history, and user lifecycle tracking."
    )
    .category("Administration")
    .author("pyvelm")
    .depends("base", "admin")
    .bootstrap(False)
    .data(
        "views/audit_log.py",
        "views/login_log.py",
        "views/user_lifecycle.py",
        "views/menu.py",
    )
    .install_hook("system_audit.hooks:install")
    .web_routes("system_audit.web:register_routes")
)
