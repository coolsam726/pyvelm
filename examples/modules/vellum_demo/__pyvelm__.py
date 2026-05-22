NAME: str = "vellum_demo"
VERSION: tuple[int, ...] = (0, 3, 1)
SUMMARY: str = "Example models exercising the Vellum query builder."
CATEGORY: str = "Examples"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "vellum"]
DATA: list[str] = [
    "views/note.py",
    "views/menu.py",
]
