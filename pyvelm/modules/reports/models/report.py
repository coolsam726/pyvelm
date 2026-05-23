"""Report definition stored in the database."""
from __future__ import annotations

from pyvelm import BaseModel, Boolean, Char, Integer, Many2many, Many2one, Text


class Report(BaseModel):
    _name = "ir.report"

    name = Char(required=True)
    description = Text()
    root_model = Char(required=True)
    definition = Text(required=True)
    row_limit = Integer(default=10000)
    active = Boolean(default=True)
    group_ids = Many2many("res.groups")
    cron_id = Many2one("ir.cron", ondelete="SET NULL")
    output_format = Char(
        default="xlsx",
        choices=[
            ("xlsx", "Excel"),
            ("csv", "CSV"),
            ("pdf", "PDF"),
        ],
    )
    schedule_active = Boolean(default=False)
