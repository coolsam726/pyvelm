"""Sidebar entries for the file_manager module — top-level Files app."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("file_manager")

MENUS: list[Menu] = [
    m.group(
        "files",
        "Files",
        icon="folder",
        sequence=80,
    ),
    m.item(
        "files.library",
        "Library",
        parent="files",
        view="file_manager.file.kanban",
        perm="read",
        model="ir.attachment",
        sequence=10,
    ),
    m.item(
        "files.list",
        "All files",
        parent="files",
        view="file_manager.file.list",
        perm="read",
        model="ir.attachment",
        sequence=20,
    ),
]
