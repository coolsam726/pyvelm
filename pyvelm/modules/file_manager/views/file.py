"""Library views (list / kanban thumbnail grid / form) over ir.attachment."""

from pyvelm.builders import (
    Field,
    FormView,
    KanbanCard,
    KanbanView,
    ListView,
    ViewsData,
)

views_data = (
    ViewsData.make()
    .views(
        ListView.make("file_manager.file.list")
        .model("ir.attachment")
        .title("File library")
        .columns(
            [
                "name",
                "mimetype",
                "file_size",
                "res_model",
                "res_id",
                Field.make("public").toggle(),
                "created_at",
            ]
        )
        .form_view("file_manager.file.form")
        # The "+ New" button on the list jumps to the multipart upload
        # page instead of the default empty-record form (attachments
        # without bytes are useless).
        .create_href("/web/files/upload"),
        KanbanView.make("file_manager.file.kanban")
        .model("ir.attachment")
        .title("File library")
        .card(
            KanbanCard.make("name")
            .image("thumbnail_url")
            .subtitle("mimetype")
            .fields(["file_size", "res_model"])
            .badges([Field.make("public").toggle()])
        )
        .form_view("file_manager.file.form"),
        FormView.make("file_manager.file.form")
        .model("ir.attachment")
        .title("File")
        .cols(2)
        .section(
            "identity",
            "File",
            [
                "name",
                "datas_fname",
                "mimetype",
                "file_size",
                "type",
                Field.make("public").toggle(),
            ],
        )
        .section(
            "owner",
            "Linked record",
            [
                Field.make("res_model").widget("model"),
                "res_id",
            ],
        )
        .section(
            "storage",
            "Storage",
            [
                Field.make("url").colspan("full"),
                "storage_key",
            ],
            cols=1,
        )
        .section(
            "metadata",
            "Metadata",
            ["created_at", "updated_at"],
        ),
    )
)
