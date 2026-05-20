from pyvelm.types import View

VIEWS: list[View] = [
    {
        "name": "lead.list",
        "model": "crm.lead",
        "view_type": "list",
        "arch": {
            "title": "All Leads",
            "form_view": "lead.form",
            "fields": [
                "name",
                "partner_id",
                "stage",
                {"name": "priority", "label": "Prio"},
                {"name": "expected_revenue", "label": "Revenue (k€)"},
                {"name": "probability", "label": "Prob %"},
                "salesperson",
                "label",
                "active",
            ],
        },
    },
    {
        "name": "lead.form",
        "model": "crm.lead",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "main",
                    "title": "Opportunity",
                    "fields": ["name", "partner_id", "stage", "priority"],
                },
                {
                    "name": "financials",
                    "title": "Financials",
                    "fields": ["expected_revenue", "probability", "salesperson"],
                },
                {
                    "name": "meta",
                    "title": "Meta",
                    "fields": ["company_id", "active"],
                },
            ],
        },
    },
    {
        "name": "lead.kanban",
        "model": "crm.lead",
        "view_type": "kanban",
        "arch": {
            "title": "Pipeline",
            "group_by": "stage",
            "form_view": "lead.form",
            "card": {
                "title": "name",
                "subtitle": "salesperson",
                "fields": [
                    {"name": "partner_id", "label": "Contact"},
                    {"name": "expected_revenue", "label": "Revenue (k€)"},
                    {"name": "probability", "label": "Prob %"},
                ],
                "badges": ["active"],
            },
        },
    },
]
