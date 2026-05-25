"""Tests for workflow history timeline helpers."""
from __future__ import annotations

import pytest

from pyvelm.workflow.history import classify_workflow_body


@pytest.mark.parametrize(
    "body, kind, variant",
    [
        ("Workflow started — state «draft»", "started", "brand"),
        ("Submitted for approval — «Submit»", "submitted", "warning"),
        ("Approval rejected — returned to «draft»", "rejected", "danger"),
        ("Approved — moved to «done»", "approved", "success"),
        ("«Submit for approval» approved — now at «Under review»", "signoff", "success"),
        ("Moved to «review» via «Submit»", "transition", "success"),
        ("Something else", "note", "muted"),
    ],
)
def test_classify_workflow_body(body, kind, variant):
    assert classify_workflow_body(body) == (kind, variant)
