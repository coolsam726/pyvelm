"""Library views (list / kanban thumbnail grid / form) over ir.attachment."""

from pyvelm.builders import (
    card,
    field,
    form_view,
    kanban_view,
    list_view,
    section,
)
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "file_manager.file.list",
        "ir.attachment",
        title="File library",
        fields=[
            "name",
            "mimetype",
            "file_size",
            "res_model",
            "res_id",
            field("public", widget="toggle"),
            "created_at",
        ],
        form_view="file_manager.file.form",
        # The "+ New" button on the list jumps to the multipart upload
        # page instead of the default empty-record form (attachments
        # without bytes are useless).
        create_href="/web/files/upload",
    ),
    kanban_view(
        "file_manager.file.kanban",
        "ir.attachment",
        title="File library",
        card=card(
            "name",
            image="thumbnail_url",
            subtitle="mimetype",
            fields=["file_size", "res_model"],
            badges=[field("public", widget="toggle")],
        ),
        form_view="file_manager.file.form",
    ),
    form_view(
        "file_manager.file.form",
        "ir.attachment",
        title="File",
        cols=2,
        sections=[
            section(
                "identity",
                "File",
                [
                    "name",
                    "datas_fname",
                    "mimetype",
                    "file_size",
                    "type",
                    field("public", widget="toggle"),
                ],
            ),
            section(
                "owner",
                "Linked record",
                [
                    field("res_model", widget="model"),
                    "res_id",
                ],
            ),
            section(
                "storage",
                "Storage",
                [
                    field("url", colspan="full"),
                    "storage_key",
                ],
                cols=1,
            ),
            section(
                "metadata",
                "Metadata",
                ["created_at", "updated_at"],
            ),
        ],
    ),
]
