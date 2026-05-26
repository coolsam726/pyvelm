"""Views for workflow definitions."""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "workflow_definition.list",
        "workflow.definition",
        title="Workflow definitions",
        fields=["name", "model", field("active", widget="toggle")],
        create_href="/web/workflow/build",
        record_href="/web/workflow/{id}/build",
    ),
    form_view(
        "workflow_definition.form",
        "workflow.definition",
        header_actions=[
            {
                "label": "Open designer",
                "url": "/web/workflow/{id}/build",
                "method": "GET",
                "full_page": True,
                "perm": "write",
            },
        ],
        sections=[
            section("main", "Workflow", [
                "name", "description", "model",
                field("active", widget="toggle"),
            ]),
            section("access", "Access", ["group_ids"]),
        ],
    ),
]
