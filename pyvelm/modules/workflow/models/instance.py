"""Running workflow instance bound to a business record."""
from __future__ import annotations

from pyvelm import BaseModel, Boolean, Char, Integer, Many2one, Text
from pyvelm.cron import _DatetimeField


class WorkflowInstance(BaseModel):
    _name = "workflow.instance"

    definition_id = Many2one("workflow.definition", required=True, ondelete="CASCADE")
    res_model = Char(required=True)
    res_id = Integer(required=True)
    state = Char(required=True)
    pending_transition = Char()
    stage_data = Text(default="{}")
    started_by = Many2one("res.users", ondelete="SET NULL")
    state_updated_at = _DatetimeField()
    active = Boolean(default=True)
