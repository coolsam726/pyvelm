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
        # Drive-style shell with folder tree + selection + details
        # panel; uses /web/files/library instead of the bare kanban
        # so the surrounding chrome (tree, action bar) is in place.
        href="/web/files/library",
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
    m.item(
        "files.folders",
        "Folders",
        parent="files",
        view="file_manager.folder.list",
        perm="read",
        model="res.attachment.folder",
        sequence=30,
    ),
]
