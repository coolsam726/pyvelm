"""Audit log for report executions."""
from __future__ import annotations

from pyvelm import BaseModel, Char, Integer, Many2one, Text


class ReportRun(BaseModel):
    _name = "ir.report.run"

    report_id = Many2one("ir.report", required=True, ondelete="CASCADE")
    user_id = Many2one("res.users", ondelete="SET NULL")
    row_count = Integer(default=0)
    duration_ms = Integer(default=0)
    format = Char(default="preview")
    state = Char(default="done")
    error_message = Text()
