NAME: str = "vellum_demo"
DISPLAY_NAME: str = "Vellum Demo"
VERSION: tuple[int, ...] = (0, 3, 2)
SUMMARY: str = "Example models exercising the Vellum query builder."
CATEGORY: str = "Demo"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "vellum"]
DATA: list[str] = [
    "views/note.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "vellum_demo.hooks:install"
SYNC_HOOK: str = "vellum_demo.hooks:sync"
