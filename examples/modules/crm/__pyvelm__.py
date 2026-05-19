NAME: str = "crm"
VERSION: tuple[int, ...] = (0, 1, 0)
DEPENDS: list[str] = ["base", "partners"]
DATA: list[str] = [
    "views/lead.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "crm.hooks:install"
