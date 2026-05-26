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
    # Keep access seeds consistent with the rest of the framework: Admin
    # gets full CRUD, internal User typically gets read so list/form pages
    # can render without throwing PermissionError on relational hops.
    from pyvelm.security import grant_model_access

    # Design-time workflow definitions remain admin-only.
    grant_model_access(env, "workflow.definition", admin="crud", user=None)
    # Runtime workflow: internal users reach the inbox via
    # ``workflow.approval`` read; instance/task admin lists stay admin-only.
    # Record pages still show workflow state via targeted sudo in the
    # workflow service when the user lacks instance read.
    grant_model_access(env, "workflow.instance", admin="crud", user=None)
    grant_model_access(env, "workflow.approval", admin="crud", user="read")
    grant_model_access(env, "workflow.task", admin="crud", user=None)
    _drop_legacy_user_read_on(env, ("workflow.instance", "workflow.task"))

    Definition = env["workflow.definition"]
    _upsert_partner_workflow(Definition)

    _seed_escalation_cron(env)


def sync(env):
    """Refresh bundled demo definitions (e.g. after workflow JSON changes)."""
    _drop_legacy_user_read_on(env, ("workflow.instance", "workflow.task"))
    if "workflow.definition" in env.registry:
        _upsert_partner_workflow(env["workflow.definition"])
    _seed_escalation_cron(env)


def _drop_legacy_user_read_on(env, models: tuple[str, ...]) -> None:
    """Remove obsolete ``User/…`` read rows left from older workflow ACL seeds."""
    if "ir.model.access" not in env.registry:
        return
    from pyvelm.security import GROUP_USER, _group_by_name

    grp = _group_by_name(env, GROUP_USER)
    if not grp:
        return
    Access = env["ir.model.access"]
    for model in models:
        for row in Access.search(
            [("name", "=", f"User/{model}"), ("group_id", "=", grp.id)]
        ):
            row.unlink()


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
