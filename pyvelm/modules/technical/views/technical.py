"""Low-level record editors exposed by the technical module.

Views over ``ir.ui.menu``, ``ir.ui.view``, and ``ir.attachment``. The
arch / operations bodies use the ``Code`` widget with language ``json``
so the operator gets syntax highlighting + line numbers when editing
view inheritance ops or arch payloads.
"""

from pyvelm.builders import (
    field,
    form_view,
    list_view,
    section,
)
from pyvelm.types import View

VIEWS: list[View] = [
    # ---- ir.ui.menu ----------------------------------------------------
    list_view(
        "technical.menu.list",
        "ir.ui.menu",
        title="Menu entries",
        fields=[
            "module",
            "name",
            "label",
            "parent_id",
            "sequence",
            "href",
            field("active", widget="toggle"),
            field("dev_only", widget="toggle"),
        ],
        form_view="technical.menu.form",
    ),
    form_view(
        "technical.menu.form",
        "ir.ui.menu",
        title="Menu entry",
        cols=2,
        sections=[
            section(
                "identity",
                "Identity",
                [
                    "module",
                    "name",
                    "label",
                    "parent_id",
                    "sequence",
                    field("active", widget="toggle"),
                    field("dev_only", widget="toggle"),
                ],
            ),
            section(
                "target",
                "Target",
                [
                    field("href", colspan="full"),
                    field("icon", colspan="full"),
                ],
                cols=1,
            ),
            section(
                "access",
                "Access gate",
                [
                    "access_model",
                    "access_perm",
                    "access_policy",
                ],
            ),
        ],
    ),
    # ---- ir.ui.view ----------------------------------------------------
    list_view(
        "technical.view.list",
        "ir.ui.view",
        title="Views",
        fields=[
            "module",
            "name",
            field("model", widget="model"),
            "view_type",
            "priority",
            "inherit_id",
        ],
        form_view="technical.view.form",
    ),
    form_view(
        "technical.view.form",
        "ir.ui.view",
        title="View",
        cols=2,
        sections=[
            section(
                "identity",
                "Identity",
                [
                    "module",
                    "name",
                    field("model", widget="model"),
                    "view_type",
                    "priority",
                    "inherit_id",
                ],
            ),
            section(
                "arch",
                "Arch (JSON)",
                [field("arch", widget="code", language="json")],
                cols=1,
            ),
            section(
                "operations",
                "Extension operations (JSON)",
                [field("operations", widget="code", language="json")],
                cols=1,
            ),
        ],
    ),
    # ---- ir.attachment -------------------------------------------------
    list_view(
        "technical.attachment.list",
        "ir.attachment",
        title="Attachments",
        fields=[
            "name",
            "res_model",
            "res_id",
            "mimetype",
            "file_size",
            field("public", widget="toggle"),
            "type",
        ],
        form_view="technical.attachment.form",
    ),
    form_view(
        "technical.attachment.form",
        "ir.attachment",
        title="Attachment",
        cols=2,
        sections=[
            section(
                "identity",
                "Identity",
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
                    "res_model",
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
            ),
        ],
    ),
]
