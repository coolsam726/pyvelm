"""Views for workflow definitions."""

from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("workflow_definition.list")
        .model("workflow.definition")
        .title("Workflow definitions")
        .columns(["name", "model", Field.make("active").toggle()])
        .create_href("/web/workflow/build")
        .record_href("/web/workflow/{id}/build"),
        FormView.make("workflow_definition.form")
        .model("workflow.definition")
        .header_actions(
            [
                {
                    "label": "Open designer",
                    "url": "/web/workflow/{id}/build",
                    "method": "GET",
                    "full_page": True,
                    "perm": "write",
                },
            ]
        )
        .section(
            "main",
            "Workflow",
            [
                "name",
                "description",
                "model",
                Field.make("active").toggle(),
            ],
        )
        .section("access", "Access", ["group_ids"]),
    )
)
