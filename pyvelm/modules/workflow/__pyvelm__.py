NAME: str = "workflow"
DISPLAY_NAME: str = "Workflows"
VERSION: tuple[int, ...] = (0, 2, 0)
SUMMARY: str = (
    "Visual approval and task workflows — state machines, stage forms, "
    "and multi-step sign-off on any model."
)
CATEGORY: str = "System"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/definition.py",
    "views/runtime.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "workflow.hooks:install"
