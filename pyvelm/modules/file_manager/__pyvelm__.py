NAME: str = "file_manager"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "File library + file-picker widget over ir.attachment."
CATEGORY: str = "System"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/file.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "file_manager.hooks:install"
