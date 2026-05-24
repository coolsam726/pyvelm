"""Runtime workflow views — instances, approvals, tasks."""

from pyvelm.builders import field, form_view, list_view, section
from pyvelm.types import View

VIEWS: list[View] = [
    list_view(
        "workflow_instance.list",
        "workflow.instance",
        title="Workflow instances",
        fields=[
            "definition_id", "res_model", "res_id", "state",
            "pending_transition", "started_by",
        ],
    ),
    form_view(
        "workflow_instance.form",
        "workflow.instance",
        sections=[
            section("main", "Instance", [
                "definition_id", "res_model", "res_id", "state",
                "pending_transition", "started_by", "state_updated_at",
            ]),
        ],
    ),
    list_view(
        "workflow_approval.list",
        "workflow.approval",
        title="Approval requests",
        fields=[
            "instance_id", "transition_key", "status",
            "requester_id", "assignee_user_id", "assignee_group_id",
            "acted_by",
        ],
    ),
    form_view(
        "workflow_approval.form",
        "workflow.approval",
        sections=[
            section("main", "Approval", [
                "instance_id", "transition_key", "status",
                "requester_id", "assignee_user_id", "assignee_group_id",
                "acted_by", "acted_at", "comment",
            ]),
        ],
    ),
    list_view(
        "workflow_task.list",
        "workflow.task",
        title="Tasks",
        fields=[
            "name", "user_id", "state", "priority",
            "date_deadline", "res_model", "res_id",
        ],
    ),
    form_view(
        "workflow_task.form",
        "workflow.task",
        sections=[
            section("main", "Task", [
                "name", "description", "user_id", "state", "priority",
                "date_deadline", "res_model", "res_id", "instance_id",
            ]),
        ],
    ),
]
