NAME: str = "reports"
DISPLAY_NAME: str = "Report Builder"
VERSION: tuple[int, ...] = (0, 2, 0)
SUMMARY: str = "User-defined reports with secure SQL compilation and Excel export."
CATEGORY: str = "System"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/report.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "reports.hooks:install"
