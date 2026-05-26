NAME: str = "mail_compose"
VERSION: tuple[int, ...] = (0, 1, 1)
SUMMARY: str = "Rich email composer with templates, multi-recipient, Cc/Bcc, and attachments."
CATEGORY: str = "Workflows"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base", "admin"]
DATA: list[str] = [
    "views/compose.py",
    "views/menu.py",
]
INSTALL_HOOK: str = "mail_compose.hooks:install"
