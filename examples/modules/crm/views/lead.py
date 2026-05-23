"""View declarations for the ``crm`` module."""

from pyvelm.builders import (
    card,
    field,
    form_view,
    graph_view,
    kanban_view,
    list_view,
    pivot_view,
    section,
)
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "lead.list", "crm.lead",
        title="All Leads",
        form_view="lead.form",
        fields=[
            "name",
            "partner_id",
            "stage",
            field("priority", label="Prio"),
            field("expected_revenue", label="Revenue (k€)"),
            field("probability", label="Prob %"),
            "salesperson",
            "expected_close",
            "next_contact_at",
            "label",
            "active",
        ],
    ),

    form_view(
        "lead.form", "crm.lead",
        sections=[
            section("main",       "Opportunity", ["name", "partner_id", "stage", "priority"]),
            section("financials", "Financials",  ["expected_revenue", "probability", "salesperson"]),
            section(
                "scheduling",
                "Scheduling (date · datetime popup · time)",
                ["expected_close", "next_contact_at", "preferred_call_time"],
            ),
            section("meta",       "Meta",        ["company_id", "active"]),
        ],
    ),

    kanban_view(
        "lead.kanban", "crm.lead",
        title="Pipeline",
        group_by="stage",
        form_view="lead.form",
        card=card(
            "name",
            subtitle="salesperson",
            fields=[
                field("partner_id", label="Contact"),
                field("expected_revenue", label="Revenue (k€)"),
                field("probability", label="Prob %"),
            ],
            badges=["active"],
        ),
    ),

    graph_view(
        "lead.graph", "crm.lead",
        title="Revenue by stage",
        groupby="stage",
        measure="expected_revenue:sum",
        chart="bar",
    ),

    pivot_view(
        "lead.pivot", "crm.lead",
        title="Pipeline pivot",
        row_groupby=["stage"],
        col_groupby=["priority"],
        measures=["__count", "expected_revenue:sum"],
    ),
]
