"""View declarations for the ``partners`` module."""

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
        ListView.make("partner.list")
        .model("res.partner")
        .columns(
            [
                "name",
                "workflow_state_label",
                "code",
                "company_id",
                "age",
                "birth_date",
                "country_id",
                "active",
            ]
        )
        .form_view("partner.form"),
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code"])
        .section(
            "profile",
            "Profile",
            [
                "age",
                "birth_date",
                "country_id",
                "company_id",
                "parent_id",
                "active",
            ],
        )
        .section(
            "relations",
            "Relations",
            [
                Field.make("tag_ids").widget("dialog"),
                Field.make("child_ids").widget("dialog"),
            ],
        ),
        KanbanView.make("partner.kanban")
        .model("res.partner")
        .title("Partner Board")
        .card(
            KanbanCard.make("name")
            .subtitle("code")
            .fields(["age", "country_id"])
            .badges([Field.make("active").toggle(), "tag_ids"])
        )
        # group_by="country_id",
        .form_view("partner.form"),
        # ---- res.tag ----
        # Moved here from admin: partners owns res.tag, so it owns the
        # views too. The Settings → Tags sidebar entry (see views/menu.py)
        # still parents under admin.settings via cross-module menu refs.
        ListView.make("tag.list")
        .model("res.tag")
        # sequence opts into drag-reorder (handle column, forced sort).
        .sequence("sequence")
        .columns(["name"]),
        FormView.make("tag.form")
        .model("res.tag")
        .section("main", "Tag", ["name"]),
    )
)
