"""Inherit and patch the base `partners.partner.list` view.

Demonstrates each operation kind:
  - remove         : drop a field from the list
  - after          : positional insertion
  - update         : merge multiple attributes into a target dict (the
                     Odoo `position="attributes"` ergonomic — terse when
                     you have several attrs to set on the same field)
  - set            : add a single new attribute (granular)

The last inherit on this list (`partner.form.pro.xpath`) demos
Stage 7 Slice C extensions:
  - dict-segment **predicates** to match list entries by any attribute
  - `"**"` **wildcard** to find a node anywhere in the arch
"""

from pyvelm.types import ViewInherit

VIEW_INHERITS: list[ViewInherit] = [
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
            # Add a new VIP section with the vip_note field (Stage 7).
            {
                "op": "after",
                "target": ["sections", "relations"],
                "value": {
                    "name": "vip",
                    "title": "VIP Status",
                    "fields": ["vip_note"],
                },
            },
        ],
    },

    # ── Stage 7 Slice C: predicate + wildcard target segments ──
    #
    # Both ops below would be impossible / awkward in pure dict-op
    # form: the first needs to match by an attribute other than
    # `name`; the second doesn't care which section `tag_ids` lives
    # in. Practical effect on the partner form: every field-spec
    # tagged `widget="toggle"` becomes readonly, and `tag_ids`
    # picks up a label without us hard-coding the section path.
    {
        "name": "partner.form.pro.xpath",
        "inherit": "partners.partner.form",
        "priority": 30,
        "operations": [
            # Predicate segment: match any field-spec inside the
            # profile section's fields list whose `widget == "toggle"`.
            # Today only `active` has that hint applied (set by the
            # earlier inherit), so the update lands there.
            {
                "op": "update",
                "target": [
                    "sections", "profile", "fields",
                    {"widget": "toggle"},
                ],
                "value": {"readonly": True},
            },
            # `**` wildcard: find `tag_ids` anywhere in the arch and
            # add a custom label. We don't need to know which section
            # it lives in.
            {
                "op": "set",
                "target": ["**", {"name": "tag_ids"}, "label"],
                "value": "Tags (any section)",
            },
        ],
    },
]
