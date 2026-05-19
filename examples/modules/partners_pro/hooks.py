"""Install hook for partners_pro.

Demonstrates non-admin access patterns: a `Partner Manager` group
with read/write (no create/unlink) on res.partner, scoped by a
record rule to active partners only. Plus a `manager` user in that
group so the smoke test can authenticate as someone-other-than-admin.
"""

import json


def install(env):
    Group = env["res.groups"]
    User = env["res.users"]
    Access = env["ir.model.access"]
    Rule = env["ir.rule"]

    pm = Group.create({"name": "Partner Manager"})
    User.create({
        "name": "Manager",
        "login": "manager",
        "password": "manager",
        "group_ids": [pm],
    })

    # Read + write only; no create or unlink.
    Access.create({
        "name": "PartnerManager/res.partner",
        "model": "res.partner",
        "group_id": pm,
        "perm_read": True,
        "perm_write": True,
    })
    # Also let them read countries/regions for the form's Many2one
    # dropdown to populate. (Public already grants this; the row is
    # redundant but explicit.)
    for model in ("res.country", "res.region", "res.tag"):
        Access.create({
            "name": f"PartnerManager/{model}",
            "model": model,
            "group_id": pm,
            "perm_read": True,
        })

    # Record rule: Partner Manager only sees *active* partners.
    Rule.create({
        "name": "PM: active partners only",
        "model": "res.partner",
        "group_id": pm,
        "perm_read": True,
        "perm_write": True,
        "domain": json.dumps([["active", "=", True]]),
    })
