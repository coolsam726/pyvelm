"""Standalone tasks — assignments outside a formal approval chain."""
from __future__ import annotations

from pyvelm import BaseModel, Char, Integer, Many2one, Text
from pyvelm.cron import _DatetimeField


class WorkflowTask(BaseModel):
    _name = "workflow.task"

    name = Char(required=True)
    description = Text()
    user_id = Many2one("res.users", ondelete="SET NULL")
    date_deadline = _DatetimeField()
    state = Char(
        default="open",
        choices=[
            ("open", "Open"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
    )
    priority = Char(
        default="normal",
        choices=[
            ("low", "Low"),
            ("normal", "Normal"),
            ("high", "High"),
        ],
    )
    res_model = Char()
    res_id = Integer()
    instance_id = Many2one("workflow.instance", ondelete="SET NULL")
