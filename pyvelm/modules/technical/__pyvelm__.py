NAME: str = "technical"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "Developer-only editors for low-level records (ir.ui.menu, ir.ui.view, ir.attachment)."
CATEGORY: str = "System"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/technical.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "technical.hooks:install"

# Hide the module from the Apps catalog for non-admin users; the admin
# UI is the only way to install it.
CATALOG_ACCESS_MODEL: str = "res.users"
CATALOG_ACCESS_PERM: str = "write"
