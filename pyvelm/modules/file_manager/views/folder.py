"""Admin list + form for ``res.attachment.folder``.

The main UX is the folder tree inside the Library page; these views
exist for the rare case where an admin wants to bulk-rename or fix
parent links via the standard CRUD plumbing.
"""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "file_manager.folder.list",
        "res.attachment.folder",
        title="Folders",
        fields=["display_name", "name", "parent_id", "sequence", "color"],
        form_view="file_manager.folder.form",
    ),
    form_view(
        "file_manager.folder.form",
        "res.attachment.folder",
        title="Folder",
        sections=[
            section(
                "identity",
                "Identity",
                ["name", "parent_id", "sequence", field("color", widget="color")],
            ),
        ],
    ),
]
