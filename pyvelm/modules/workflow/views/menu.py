"""Menu entries under Admin → Workflows (level-3 leaves)."""

from pyvelm.builders import Menus, ViewsData

m = Menus("workflow")

views_data = (
    ViewsData.make()
    .menus(
        m.item(
            "workflow.inbox",
            "My approvals",
            parent=("admin", "workflows.operations"),
            href="/web/workflow/inbox",
            sequence=5,
            model="workflow.approval",
            policy="inbox",
        ),
        m.item(
            "workflow.design",
            "Design workflow",
            parent=("admin", "workflows.configuration"),
            href="/web/workflow/build",
            sequence=5,
            model="workflow.definition",
            policy="design",
        ),
        m.item(
            "workflow.definitions",
            "Definitions",
            parent=("admin", "workflows.configuration"),
            view="workflow_definition.list",
            sequence=15,
            policy="view_any",
        ),
    )
)
