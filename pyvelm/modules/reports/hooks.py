"""Install hook for the reports module."""

from __future__ import annotations

import json

_DEMO_USERS_REPORT = {
    "version": 1,
    "root": "res.users",
    "columns": [
        {"expr": "name", "label": "Name"},
        {"expr": "login", "label": "Login"},
        {"expr": "active", "label": "Active"},
    ],
    "filters": [],
    "order": ["name asc"],
    "parameters": [
        {
            "name": "name_contains",
            "type": "string",
            "label": "Name contains",
            "required": False,
        }
    ],
    "parameter_filters": [
        ["name", "ilike", {"param": "name_contains"}],
    ],
}


def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    for model in ("ir.report", "ir.report.run", "ir.cron", "ir.actions.server"):
        Access.create({
            "name": f"Admin/{model}",
            "model": model,
            "group_id": admin,
            "perm_read": True,
            "perm_write": True,
            "perm_create": True,
            "perm_unlink": True,
        })

    Report = env["ir.report"]
    if not Report.search([("name", "=", "Active users")]):
        Report.create({
            "name": "Active users",
            "description": "Directory of user accounts with optional name filter.",
            "root_model": "res.users",
            "definition": json.dumps(_DEMO_USERS_REPORT, indent=2),
            "row_limit": 10000,
            "active": True,
        })
