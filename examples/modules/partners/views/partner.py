"""View declarations for the ``partners`` module."""

from __future__ import annotations

from pyvelm.builders import (
    Action,
    ActionForm,
    Field,
    FormView,
    KanbanCard,
    KanbanView,
    ListView,
    Page,
    ViewsData,
)


def _parent_options_domain(record, env, get) -> list:
    """Filter parent contacts to the selected company (schema ``options_domain``)."""
    company_id = get("company_id")
    if company_id:
        return [("company_id", "=", company_id)]
    return [("id", "=", -1)]

views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .page_actions(
            [
                Action.make("Quick add")
                .model("res.partner")
                .perm("create")
                .form(
                    lambda form: form.section(
                        "identity",
                        "Quick contact",
                        [
                            "name",
                            "country_id",
                            Field.make("active").toggle(),
                        ],
                    )
                ),
            ]
        )
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
                # Filament-style schema: live re-render + domain visibility.
                Field.make("age").live(debounce=200),
                Field.make("birth_date").visible_when([("age", ">=", 18)]),
                # ``email`` is an inferred live driver (phone predicates).
                "email",
                Field.make("phone")
                .visible_when([("email", "like", "@")])
                .required_when([("email", "like", "@")]),
                "country_id",
                Field.make("company_id").live(),
                # Callable when empty-company → no matches; or static domain:
                # .options_domain([("company_id", "=", "company_id")])
                Field.make("parent_id")
                .depends_on("company_id")
                .options_domain(_parent_options_domain),
                # Nested domain example (SQL + live forms):
                # .visible_when([("company_id.currency_id.code", "=", "KES")])
                Field.make("active").live(on_blur=True),
            ],
        )
        .notebook(
            "relations",
            "Relations",
            [
                Page.make("tags", "Tags")
                .fields([Field.make("tag_ids").widget("dialog")]),
                Page.make("children", "Contacts")
                .fields([Field.make("child_ids").widget("dialog")]),
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
