"""Admin list + form for ``res.attachment.folder``.

The main UX is the folder tree inside the Library page; these views
exist for the rare case where an admin wants to bulk-rename or fix
parent links via the standard CRUD plumbing.
"""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("file_manager.folder.list")
        .model("res.attachment.folder")
        .title("Folders")
        .columns(["display_name", "name", "parent_id", "sequence", "color"])
        .form_view("file_manager.folder.form"),
        FormView.make("file_manager.folder.form")
        .model("res.attachment.folder")
        .title("Folder")
        .section(
            "identity",
            "Identity",
            ["name", "parent_id", "sequence", Field.make("color").widget("color")],
        ),
    )
)
