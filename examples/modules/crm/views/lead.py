"""View declarations for the ``crm`` module."""

from pyvelm.builders import (
    Field,
    FormView,
    GraphView,
    KanbanCard,
    KanbanView,
    ListView,
    PivotView,
    ViewsData,
)

views_data = (
    ViewsData.make()
    .views(
        ListView.make("lead.list")
        .model("crm.lead")
        .title("All Leads")
        .form_view("lead.form")
        .columns(
            [
                "name",
                "partner_id",
                "stage",
                Field.make("priority").label("Prio"),
                Field.make("expected_revenue").label("Revenue (k€)"),
                Field.make("probability").label("Prob %"),
                "salesperson",
                "expected_close",
                "next_contact_at",
                "label",
                "active",
            ]
        ),
        FormView.make("lead.form")
        .model("crm.lead")
        .section("main", "Opportunity", ["name", "partner_id", "stage", "priority"])
        .section(
            "financials",
            "Financials",
            ["expected_revenue", "probability", "salesperson"],
        )
        .section(
            "scheduling",
            "Scheduling (date · datetime popup · time)",
            ["expected_close", "next_contact_at", "preferred_call_time"],
        )
        .section("meta", "Meta", ["company_id", "active"]),
        KanbanView.make("lead.kanban")
        .model("crm.lead")
        .title("Pipeline")
        .group_by("stage")
        .form_view("lead.form")
        .card(
            KanbanCard.make("name")
            .subtitle("salesperson")
            .fields(
                [
                    Field.make("partner_id").label("Contact"),
                    Field.make("expected_revenue").label("Revenue (k€)"),
                    Field.make("probability").label("Prob %"),
                ]
            )
            .badges(["active"])
        ),
        GraphView.make("lead.graph")
        .model("crm.lead")
        .title("Revenue by stage")
        .groupby("stage")
        .measure("expected_revenue:sum")
        .chart("bar"),
        PivotView.make("lead.pivot")
        .model("crm.lead")
        .title("Pipeline pivot")
        .row_groupby(["stage"])
        .col_groupby(["priority"])
        .measures(["__count", "expected_revenue:sum"]),
    )
)
