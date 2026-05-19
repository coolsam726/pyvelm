NAME: str = "partners"
VERSION: tuple[int, ...] = (0, 2, 0)
DEPENDS: list[str] = ["base"]
DATA: list[str] = [
    "views/partner.py",
]
INSTALL_HOOK: str = "partners.hooks:install"
