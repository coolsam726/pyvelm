"""View declarations for the `partners` module.

Each module-level list (`VIEWS`, `VIEW_INHERITS`, future `RECORDS`)
is picked up by the loader when this file is named in the manifest's
DATA list.
"""

VIEWS = [
    {
        "name": "partner.list",
        "model": "res.partner",
        "view_type": "list",
        "arch": {
            "fields": ["name", "code", "age", "country_id", "active"],
        },
    },
    {
        "name": "partner.form",
        "model": "res.partner",
        "view_type": "form",
        "arch": {
            "sections": [
                {
                    "name": "identity",
                    "title": "Identity",
                    "fields": ["name", "code"],
                },
                {
                    "name": "profile",
                    "title": "Profile",
                    "fields": ["age", "country_id", "parent_id", "active"],
                },
                {
                    "name": "relations",
                    "title": "Relations",
                    "fields": ["tag_ids", "child_ids"],
                },
            ],
        },
    },
    {
        "name": "partner.kanban",
        "model": "res.partner",
        "view_type": "kanban",
        "arch": {
            # `title` / `subtitle` are field references rendered with
            # the field's default display widget. `fields` shows
            # label/value pairs; `badges` renders small chip-like
            # indicators (typically booleans or short collections).
            "card": {
                "title": "name",
                "subtitle": "code",
                "fields": ["age", "country_id"],
                "badges": [
                    {"name": "active", "widget": "toggle"},
                    "tag_ids",
                ],
            },
            # Group cards into columns by country (Many2one).
            "group_by": "country_id",
            # Make each card a link to the form view for the same model.
            "form_view": "partner.form",
        },
    },
]
