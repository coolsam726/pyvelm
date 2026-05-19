"""Inherit and patch the base `partners.partner.list` view.

Demonstrates each operation kind:
  - remove         : drop a field from the list
  - after          : positional insertion
  - update         : merge multiple attributes into a target dict (the
                     Odoo `position="attributes"` ergonomic — terse when
                     you have several attrs to set on the same field)
  - set            : add a single new attribute (granular)
"""

VIEW_INHERITS = [
    {
        "name": "partner.list.pro",
        "inherit": "partners.partner.list",
        "priority": 20,
        "operations": [
            # Remove the age column.
            {"op": "remove", "target": ["fields", "age"]},

            # Insert tag_ids after country_id (positional).
            {
                "op": "after",
                "target": ["fields", "country_id"],
                "value": {"name": "tag_ids"},
            },

            # Decorate `active` with multiple attributes at once.
            {
                "op": "update",
                "target": ["fields", "active"],
                "value": {"widget": "toggle", "readonly": True},
            },

            # Granular single-attribute set: add a `label` to `code`.
            {
                "op": "set",
                "target": ["fields", "code", "label"],
                "value": "Partner code",
            },
        ],
    },
    {
        # Section-level inheritance: target a field inside a specific
        # section of the form arch. Same op vocabulary as list views,
        # just deeper paths.
        "name": "partner.form.pro",
        "inherit": "partners.partner.form",
        "priority": 20,
        "operations": [
            # Re-label the profile section.
            {
                "op": "set",
                "target": ["sections", "profile", "title"],
                "value": "Demographics",
            },
            # Push the `active` field with a toggle widget hint.
            {
                "op": "update",
                "target": ["sections", "profile", "fields", "active"],
                "value": {"widget": "toggle"},
            },
            # Drop `parent_id` from the profile section.
            {
                "op": "remove",
                "target": ["sections", "profile", "fields", "parent_id"],
            },
        ],
    },
]
