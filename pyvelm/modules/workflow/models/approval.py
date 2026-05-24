"""Approval step while a transition awaits sign-off."""
from __future__ import annotations

from pyvelm import BaseModel, Char, Integer, Many2one, Text
from pyvelm.cron import _DatetimeField


class WorkflowApproval(BaseModel):
    _name = "workflow.approval"

    instance_id = Many2one("workflow.instance", required=True, ondelete="CASCADE")
    transition_key = Char(required=True)
    status = Char(
        required=True,
        default="pending",
        choices=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
    )
    requester_id = Many2one("res.users", ondelete="SET NULL")
    assignee_user_id = Many2one("res.users", ondelete="SET NULL")
    assignee_group_id = Many2one("res.groups", ondelete="SET NULL")
    acted_by = Many2one("res.users", ondelete="SET NULL")
    acted_at = _DatetimeField()
    comment = Text()
    sequence = Integer(default=1)
    form_data = Text(default="{}")
    deadline_at = _DatetimeField()
