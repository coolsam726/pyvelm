"""Install hook — ACL grants and retention cron."""
from __future__ import annotations

from pyvelm.security import grant_model_access
from pyvelm.timestamps import utc_now


def _seed_retention_cron(env) -> None:
    if "ir.cron" not in env.registry or "ir.actions.server" not in env.registry:
        return
    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    existing = Cron.search([("name", "=", "Audit log retention")], limit=1)
    if existing:
        return
    action = Action.search(
        [("name", "=", "Audit log retention"), ("model", "=", "ir.audit.log")],
        limit=1,
    )
    if not action:
        action = Action.create(
            {
                "name": "Audit log retention",
                "model": "ir.audit.log",
                "action_type": "audit_purge",
                "vals_json": "{}",
            }
        )
    Cron.create(
        {
            "name": "Audit log retention",
            "action_id": action.id,
            "interval_number": 1,
            "interval_type": "days",
            "nextcall": utc_now(),
            "active": True,
        }
    )


def install(env):
    grant_model_access(
        env,
        "ir.audit.log",
        admin="read",
        user=None,
    )
    grant_model_access(
        env,
        "ir.login.log",
        admin="read",
        user="read",
    )
    grant_model_access(
        env,
        "ir.user.lifecycle",
        admin="read",
        user=None,
    )
    _seed_retention_cron(env)
