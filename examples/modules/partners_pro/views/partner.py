"""Inherit and patch the base ``partners`` views.

Demonstrates each operation kind:
  - op_remove  : drop a field from the list
  - op_after   : positional insertion
  - op_update  : merge multiple attributes into a target dict (kwargs)
  - op_set     : write a single attribute at a target path

The last inherit (``partner.form.pro.xpath``) demos Stage 7 Slice C:
  - dict-segment **predicates** to match list entries by any attribute
  - ``"**"`` **wildcard** to find a node anywhere in the arch
"""

from pyvelm.builders import (
    InheritView,
    ViewsData,
    op_after,
    op_remove,
    op_set,
    op_update,
)

views_data = (
    ViewsData.make()
    .inherits(
        InheritView.make("partner.list.pro")
        .extends("partners.partner.list")
        .priority(20)
        .operations(
            [
                # Remove the age column.
                op_remove(["fields", "age"]),
                # Insert tag_ids after country_id.
                op_after(["fields", "country_id"], {"name": "tag_ids"}),
                # Decorate `active` with multiple attributes at once.
                op_update(["fields", "active"], widget="toggle", readonly=True),
                # Add a label to `code`.
                op_set(["fields", "code", "label"], "Partner code"),
            ]
        ),
        InheritView.make("partner.form.pro")
        .extends("partners.partner.form")
        .priority(20)
        .operations(
            [
                # Re-label the profile section.
                op_set(["sections", "profile", "title"], "Demographics"),
                # Push the `active` field with a toggle widget hint.
                op_update(
                    ["sections", "profile", "fields", "active"], widget="toggle"
                ),
                # Drop `parent_id` from the profile section.
                op_remove(["sections", "profile", "fields", "parent_id"]),
                # Add a new VIP section with the vip_note field (Stage 7).
                op_after(
                    ["sections", "relations"],
                    {
                        "name": "vip",
                        "title": "VIP Status",
                        "fields": ["vip_note"],
                    },
                ),
            ]
        ),
        # ── Stage 7 Slice C: predicate + wildcard target segments ──
        #
        # Predicate segments match list entries by any attribute (not just
        # `name`). The ``"**"`` wildcard descends to any node where the next
        # segment would succeed, so you don't need to hard-code the full path.
        InheritView.make("partner.form.pro.xpath")
        .extends("partners.partner.form")
        .priority(30)
        .operations(
            [
                # Match any field-spec with widget=="toggle" inside the
                # profile section and mark it readonly.
                op_update(
                    ["sections", "profile", "fields", {"widget": "toggle"}],
                    readonly=True,
                ),
                # Find `tag_ids` anywhere in the arch and add a label
                # without knowing which section it lives in.
                op_set(["**", {"name": "tag_ids"}, "label"], "Tags (any section)"),
            ]
        ),
    )
)
