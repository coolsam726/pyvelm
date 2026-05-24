"""Optional workflow definition for feedback intakes (requires workflow module)."""

from __future__ import annotations

import json

_FEEDBACK_REVIEW_WORKFLOW = {
    "version": 1,
    "model": "feedback.intake",
    "auto_start": True,
    "states": [
        {"key": "new", "label": "New", "initial": True},
        {"key": "review", "label": "In review"},
        {"key": "verified", "label": "Verified", "final": True},
        {"key": "dismissed", "label": "Dismissed", "cancelled": True},
    ],
    "transitions": [
        {
            "key": "send_review",
            "label": "Send for review",
            "from": ["new"],
            "to": "review",
            "kind": "approval",
            "approval": {
                "strategy": "any",
                "assignee_type": "group",
                "deadline_hours": 48,
            },
            "form": {
                "title": "Review notes",
                "fields": [
                    {
                        "name": "review_note",
                        "label": "Reviewer note",
                        "type": "text",
                        "source": "stage",
                        "required": True,
                    },
                ],
            },
            "reject_to": "dismissed",
        },
        {
            "key": "mark_verified",
            "label": "Mark verified",
            "from": ["review"],
            "to": "verified",
            "kind": "user",
        },
    ],
}


def seed_feedback_workflow(env) -> bool:
    """Create the intake review workflow if the workflow module is installed."""
    if "workflow.definition" not in env.registry:
        return False
    Definition = env["workflow.definition"]
    if Definition.search([("name", "=", "Feedback intake review")]):
        return False
    Definition.create({
        "name": "Feedback intake review",
        "description": "Optional review step before marking feedback as verified.",
        "model": "feedback.intake",
        "definition": json.dumps(_FEEDBACK_REVIEW_WORKFLOW, indent=2),
        "active": True,
    })
    return True


def backfill_intake_workflows(env) -> int:
    """Start workflows on intakes that existed before the workflow was installed."""
    from pyvelm.workflow.service import backfill_auto_start

    return backfill_auto_start(env, "feedback.intake")
