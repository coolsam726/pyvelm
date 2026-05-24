"""Sidebar entries under Admin → Workflows."""

from pyvelm.builders import Menus
from pyvelm.types import Menu

m = Menus("workflow")

MENUS: list[Menu] = [
    m.item(
        "workflow.inbox",
        "My approvals",
        parent=("admin", "workflows"),
        href="/web/workflow/inbox",
        sequence=3,
    ),
    m.item(
        "workflow.design",
        "Design workflow",
        parent=("admin", "workflows"),
        href="/web/workflow/build",
        sequence=5,
    ),
    m.item(
        "workflow.definitions",
        "Definitions",
        parent=("admin", "workflows"),
        view="workflow_definition.list",
        sequence=15,
    ),
    m.item(
        "workflow.instances",
        "Instances",
        parent=("admin", "workflows"),
        view="workflow_instance.list",
        sequence=25,
    ),
    m.item(
        "workflow.approvals",
        "Approvals",
        parent=("admin", "workflows"),
        view="workflow_approval.list",
        sequence=35,
    ),
    m.item(
        "workflow.tasks",
        "Tasks",
        parent=("admin", "workflows"),
        view="workflow_task.list",
        sequence=45,
    ),
]
