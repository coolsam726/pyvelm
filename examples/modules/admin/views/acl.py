"""View declarations for the admin module.

Provides list + form views for the four ACL models that live in base:
  - res.groups       (groups)
  - res.users        (users)
  - ir.model.access  (access control entries)
  - ir.rule          (record rules / row-level security)

These are just regular pyvelm views — the admin module ships no custom
Python models; it reuses the ones defined in base.
"""
from pyvelm.types import View

VIEWS: list[View] = [
    # ---- res.groups ----
    {
        "name": "group.list",
        "model": "res.groups",
        "view_type": "list",
        "arch": {
            "fields": ["name"],
        },
    },
    {
        "name": "group.form",
        "model": "res.groups",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "main",
                    "title": "Group",
                    "fields": ["name"],
                },
                {
                    "name": "members",
                    "title": "Members",
                    "fields": ["user_ids"],
                },
            ],
        },
    },

    # ---- res.users ----
    {
        "name": "user.list",
        "model": "res.users",
        "view_type": "list",
        "arch": {
            "fields": [
                "name",
                "login",
                {"name": "active", "widget": "toggle"},
            ],
        },
    },
    {
        "name": "user.form",
        "model": "res.users",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "identity",
                    "title": "Identity",
                    "fields": [
                        "name",
                        "login",
                        "password",
                        {"name": "active", "widget": "toggle"},
                    ],
                },
                {
                    "name": "groups",
                    "title": "Groups",
                    "fields": ["group_ids"],
                },
            ],
        },
    },

    # ---- ir.model.access ----
    {
        "name": "access.list",
        "model": "ir.model.access",
        "view_type": "list",
        "arch": {
            "fields": [
                "name",
                "model",
                "group_id",
                {"name": "perm_read", "widget": "toggle"},
                {"name": "perm_write", "widget": "toggle"},
                {"name": "perm_create", "widget": "toggle"},
                {"name": "perm_unlink", "widget": "toggle"},
            ],
        },
    },
    {
        "name": "access.form",
        "model": "ir.model.access",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "main",
                    "title": "Access Rule",
                    "fields": ["name", "model", "group_id"],
                },
                {
                    "name": "permissions",
                    "title": "Permissions",
                    "fields": [
                        {"name": "perm_read", "widget": "toggle"},
                        {"name": "perm_write", "widget": "toggle"},
                        {"name": "perm_create", "widget": "toggle"},
                        {"name": "perm_unlink", "widget": "toggle"},
                    ],
                },
            ],
        },
    },

    # ---- ir.rule ----
    {
        "name": "rule.list",
        "model": "ir.rule",
        "view_type": "list",
        "arch": {
            "fields": [
                "name",
                "model",
                "group_id",
                {"name": "perm_read", "widget": "toggle"},
                {"name": "perm_write", "widget": "toggle"},
                {"name": "perm_create", "widget": "toggle"},
                {"name": "perm_unlink", "widget": "toggle"},
            ],
        },
    },
    {
        "name": "rule.form",
        "model": "ir.rule",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "main",
                    "title": "Record Rule",
                    "fields": ["name", "model", "group_id", "domain"],
                },
                {
                    "name": "permissions",
                    "title": "Applies On",
                    "fields": [
                        {"name": "perm_read", "widget": "toggle"},
                        {"name": "perm_write", "widget": "toggle"},
                        {"name": "perm_create", "widget": "toggle"},
                        {"name": "perm_unlink", "widget": "toggle"},
                    ],
                },
            ],
        },
    },

    # ---- res.company ----
    {
        "name": "company.list",
        "model": "res.company",
        "view_type": "list",
        "arch": {
            "fields": [
                "name",
                {"name": "active", "widget": "toggle"},
            ],
        },
    },
    {
        "name": "company.form",
        "model": "res.company",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "main",
                    "title": "Company",
                    "fields": [
                        "name",
                        {"name": "active", "widget": "toggle"},
                    ],
                },
            ],
        },
    },
]
