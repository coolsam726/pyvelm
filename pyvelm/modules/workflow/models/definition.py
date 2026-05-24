"""Workflow definition — JSON state machine stored in the database."""
from __future__ import annotations

from pyvelm import BaseModel, Boolean, Char, Many2many, Text


class WorkflowDefinition(BaseModel):
    _name = "workflow.definition"

    name = Char(required=True)
    description = Text()
    model = Char(required=True)
    definition = Text(required=True)
    active = Boolean(default=True)
    group_ids = Many2many("res.groups")
