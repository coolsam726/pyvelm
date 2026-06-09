"""Sidebar entries for the file_manager module — top-level Files app."""

from pyvelm.builders import Menus, ViewsData

m = Menus("file_manager")

views_data = (
    ViewsData.make()
    .menus(
        m.group(
            "files",
            "Files",
            icon="folder",
            sequence=80,
        ).children(
            [
                m.item(
                    "files.library",
                    "Library",
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
                    view="file_manager.file.list",
                    perm="read",
                    model="ir.attachment",
                    sequence=20,
                ),
                m.item(
                    "files.folders",
                    "Folders",
                    view="file_manager.folder.list",
                    perm="read",
                    model="res.attachment.folder",
                    sequence=30,
                ),
            ]
        ),
    )
)
