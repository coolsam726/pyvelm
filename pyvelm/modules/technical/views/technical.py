"""Low-level record editors exposed by the technical module.

Views over ``ir.ui.menu``, ``ir.ui.view``, and ``ir.attachment``. The
arch / operations bodies use the ``Code`` widget with language ``json``
so the operator gets syntax highlighting + line numbers when editing
view inheritance ops or arch payloads.
"""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        # ---- ir.ui.menu ----------------------------------------------------
        ListView.make("technical.menu.list")
        .model("ir.ui.menu")
        .title("Menu entries")
        .columns(
            [
                "module",
                "name",
                "label",
                "parent_id",
                "sequence",
                "href",
                Field.make("active").toggle(),
                Field.make("dev_only").toggle(),
            ]
        )
        .form_view("technical.menu.form"),
        FormView.make("technical.menu.form")
        .model("ir.ui.menu")
        .title("Menu entry")
        .cols(2)
        .section(
            "identity",
            "Identity",
            [
                "module",
                "name",
                "label",
                "parent_id",
                "sequence",
                Field.make("active").toggle(),
                Field.make("dev_only").toggle(),
            ],
        )
        .section(
            "target",
            "Target",
            [
                Field.make("href").colspan("full"),
                Field.make("icon").colspan("full"),
            ],
            cols=1,
        )
        .section(
            "access",
            "Access gate",
            [
                "access_model",
                "access_perm",
                "access_policy",
            ],
        ),
        # ---- ir.ui.view ----------------------------------------------------
        ListView.make("technical.view.list")
        .model("ir.ui.view")
        .title("Views")
        .columns(
            [
                "module",
                "name",
                Field.make("model").widget("model"),
                "view_type",
                "priority",
                "inherit_id",
            ]
        )
        .form_view("technical.view.form"),
        FormView.make("technical.view.form")
        .model("ir.ui.view")
        .title("View")
        .cols(2)
        .section(
            "identity",
            "Identity",
            [
                "module",
                "name",
                Field.make("model").widget("model"),
                "view_type",
                "priority",
                "inherit_id",
            ],
        )
        .section(
            "arch",
            "Arch (JSON)",
            [Field.make("arch").widget("code").set(language="json")],
            cols=1,
        )
        .section(
            "operations",
            "Extension operations (JSON)",
            [Field.make("operations").widget("code").set(language="json")],
            cols=1,
        ),
        # ---- ir.attachment -------------------------------------------------
        ListView.make("technical.attachment.list")
        .model("ir.attachment")
        .title("Attachments")
        .columns(
            [
                "name",
                "res_model",
                "res_id",
                "mimetype",
                "file_size",
                Field.make("public").toggle(),
                "type",
            ]
        )
        .form_view("technical.attachment.form"),
        FormView.make("technical.attachment.form")
        .model("ir.attachment")
        .title("Attachment")
        .cols(2)
        .section(
            "identity",
            "Identity",
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
                "res_model",
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
        ),
    )
)
