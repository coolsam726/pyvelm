NAME: str = "admin"
VERSION: tuple[int, ...] = (0, 1, 0)
DEPENDS: list[str] = ["base"]
DATA: list[str] = [
    "views/acl.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "admin.hooks:install"
