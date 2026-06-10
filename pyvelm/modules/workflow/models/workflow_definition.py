"""Workflow definition — JSON state machine stored in the database."""
from __future__ import annotations

from pyvelm import Boolean, Char, Many2many, Text, models


class WorkflowDefinition(models.Model):
    _name = "workflow.definition"

    name = Char(required=True)
    description = Text()
    model = Char(required=True)
    definition = Text(required=True)
    active = Boolean(default=True)
    group_ids = Many2many("res.groups")
