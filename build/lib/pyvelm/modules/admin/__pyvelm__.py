NAME: str = "admin"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "Settings, Security, and Workflows UI for the base models."
CATEGORY: str = "System"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base"]
DATA: list[str] = [
    "views/acl.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "admin.hooks:install"
