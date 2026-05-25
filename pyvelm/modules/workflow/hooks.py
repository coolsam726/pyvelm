"""Install hook for the workflow module."""

from __future__ import annotations

import json

_DEMO_PARTNER_WORKFLOW = {
    "version": 1,
    "model": "res.partner",
    "auto_start": True,
    "states": [
        {"key": "draft", "label": "Draft", "initial": True},
        {"key": "review", "label": "Under review"},
        {"key": "approved", "label": "Approved", "final": True},
        {"key": "rejected", "label": "Rejected", "cancelled": True},
    ],
    "transitions": [
        {
            "key": "submit",
            "label": "Submit for approval",
            "from": ["draft"],
            "to": "approved",
            "kind": "approval",
            "approval": {
                "strategy": "any",
                "assignee_type": "group",
                "deadline_hours": 72,
            },
            "form": {
                "title": "Submission",
                "fields": [
                    {
                        "name": "submission_note",
                        "label": "Why should this partner be approved?",
                        "type": "text",
                        "source": "stage",
                        "required": True,
                    },
                    {
                        "name": "code",
                        "label": "Partner code",
                        "source": "record",
                        "required": False,
                    },
                ],
            },
            "reject_to": "rejected",
        },
        {
            "key": "approve_direct",
            "label": "Mark approved",
            "from": ["review"],
            "to": "approved",
            "kind": "user",
        },
        {
            "key": "reset",
            "label": "Reset to draft",
            "from": ["review", "approved", "rejected"],
            "to": "draft",
            "kind": "user",
        },
    ],
}


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    for model in (
        "workflow.definition",
        "workflow.instance",
        "workflow.approval",
        "workflow.task",
    ):
        Access.create({
            "name": f"Admin/{model}",
            "model": model,
            "group_id": admin,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        })

    Definition = env["workflow.definition"]
    _upsert_partner_workflow(Definition)

    _seed_escalation_cron(env)


def sync(env):
    """Refresh bundled demo definitions (e.g. after workflow JSON changes)."""
    if "workflow.definition" in env.registry:
        _upsert_partner_workflow(env["workflow.definition"])
    _seed_escalation_cron(env)


def _upsert_partner_workflow(Definition) -> None:
    payload = {
        "name": "Partner onboarding",
        "description": "Sample approval flow for business partners.",
        "model": "res.partner",
        "definition": json.dumps(_DEMO_PARTNER_WORKFLOW, indent=2),
        "active": True,
    }
    rec = Definition.search([("name", "=", "Partner onboarding")], limit=1)
    if rec:
        rec.write({
            "description": payload["description"],
            "definition": payload["definition"],
            "active": payload["active"],
        })
    else:
        Definition.create(payload)


def _seed_escalation_cron(env):
    """Idempotent cron that escalates overdue workflow approvals."""
    if "ir.actions.server" not in env.registry or "ir.cron" not in env.registry:
        return
    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    action_name = "Workflow approval escalation"
    cron_name = "Workflow approval escalation"

    action = Action.search([("name", "=", action_name)], limit=1)
    if not action:
        action = Action.create({
            "name": action_name,
            "model": "workflow.approval",
            "action_type": "code",
            "code": (
                "from pyvelm.workflow.escalation import process_overdue_approvals\n"
                "process_overdue_approvals(env)\n"
            ),
        })

    if not Cron.search([("name", "=", cron_name)], limit=1):
        Cron.create({
            "name": cron_name,
            "action_id": action,
            "interval_number": 15,
            "interval_type": "minutes",
            "active": True,
        })
