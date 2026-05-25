NAME: str = "partners"
VERSION: tuple[int, ...] = (0, 4, 0)
SUMMARY: str = "Companies, contacts, and the partner directory."
CATEGORY: str = "Business"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base"]
DATA: list[str] = [
    "views/partner.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "partners.hooks:install"
SYNC_HOOK: str = "partners.hooks:sync"
