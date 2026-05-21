# Extending views

A downstream module can patch a view shipped by another module
without forking it. You declare a list of **operations** that the
loader applies to the parent's arch — add a field, remove one,
override an attribute — and the resolved arch is what gets served.

Same mechanism for list, form, and kanban views; same six op kinds
in every case.

## A first example

Imagine you depend on `partners` and want to add a `tag_ids` column
to its list view, drop `age`, and turn `active` into a toggle:

```python
# partners_pro/views/partner.py
from pyvelm.builders import (
    inherit_view, op_remove, op_after, op_replace,
)

VIEW_INHERITS = [
    inherit_view(
        "partner.list.pro",                  # name for the extension
        "partners.partner.list",             # "<module>.<view_name>"
        priority=20,
        ops=[
            op_remove(["fields", "age"]),
            op_after (["fields", "country_id"], {"name": "tag_ids"}),
            op_replace(["fields", "active"],
                       {"name": "active", "widget": "toggle"}),
        ],
    ),
]
```

The loader picks this up when `partners_pro` installs. From then on,
`GET /api/views/partners/partner.list` (or the HTML page) returns
the resolved arch — patches applied in ascending `priority` order,
ties broken by install order. You address the base or the
extension by name; the response is the same.

Extensions ship a `name` so the framework can track them as records
of their own, but they don't have an arch — only the `ops` list.

## Operations

Six op kinds cover everything. Each takes a `target` (a path through
the arch) and, except for `remove`, a `value`.

| Op | Use it when |
|---|---|
| `op_set`     | Write a single attribute, optionally creating a new key on a dict |
| `op_replace` | Replace a list entry or a dict value wholesale |
| `op_update`  | Merge several attributes into a dict in one call |
| `op_remove`  | Delete the target |
| `op_before`  | Insert before a list entry |
| `op_after`   | Insert after a list entry |

`op_update` is the workhorse when you need more than one attribute
on the same field:

```python
op_update(["fields", "active"],
          widget="toggle", readonly=True, label="Active?")
```

Equivalent raw form:

```python
{"op": "update", "target": ["fields", "active"],
 "value": {"widget": "toggle", "readonly": True, "label": "Active?"}}
```

For a single attribute, `op_set` with a leaf-key target reads
naturally:

```python
op_set(["fields", "code", "label"], "Partner code")
```

## Targets

A `target` is a list of segments. The framework walks them in order
and applies the op at the final position.

| Segment | Parent must be | What it matches |
|---|---|---|
| `"field"`        | dict          | Dict key lookup |
| `"field"`        | list of dicts | The entry whose `name` equals it (shorthand for `{"name": "field"}`) |
| `0`, `1`, …      | list          | Positional index |
| `{"k": "v"}`     | list of dicts | First entry where every `k:v` matches — useful when targeting by an attribute other than `name` |
| `"**"`           | anything (first segment only) | Find any descendant where the next segment would succeed |

`["sections", "profile", "fields", "active"]` reaches the `active`
field inside the `profile` section.

Errors at any segment raise during install — there's no silent skip.

### Predicates: matching by any attribute

The dict-segment form matches by attributes other than `name`. For
example, "every field with `widget="toggle"` in the profile section
becomes readonly":

```python
op_update(
    ["sections", "profile", "fields", {"widget": "toggle"}],
    readonly=True,
)
```

This is the same idea as Odoo's `xpath="//tag[@a='x'][@b='y']"`
attribute filter, but written as a Python dict.

### `"**"`: find anywhere in the arch

Sometimes you want to patch a field without hard-coding which section
or sub-tree it lives in. Use `"**"` as the first segment and the
framework finds the first descendant where the next segment matches:

```python
# "label tag_ids regardless of which section owns it"
op_set(["**", {"name": "tag_ids"}, "label"], "Tags")
```

`"**"` is **only valid as the first segment**. The remaining segments
resolve normally against the discovered subtree. If no descendant
matches, the op raises during install — same loud-failure policy as
bad fixed-path targets.

## Form views

Same op vocabulary, deeper paths. To rename a section's title, drop
a field from a section, and add a new section:

```python
inherit_view(
    "partner.form.pro", "partners.partner.form", priority=20,
    ops=[
        op_set(["sections", "profile", "title"], "Demographics"),
        op_update(["sections", "profile", "fields", "active"],
                  widget="toggle"),
        op_remove(["sections", "profile", "fields", "parent_id"]),
        op_after(["sections", "relations"], {
            "name": "vip",
            "title": "VIP Status",
            "fields": ["vip_note"],
        }),
    ],
)
```

## Kanban views

Card-level keys (`title`, `subtitle`, `group_by`, `form_view`) are
addressed via simple `set`/`remove` at the top of the arch.
Card-field lists use the same name-shorthand rule:

```python
inherit_view(
    "lead.kanban.compact", "crm.lead.kanban", priority=20,
    ops=[
        op_set(["card", "subtitle"], "salesperson"),
        op_remove(["card", "fields", "expected_revenue"]),
    ],
)
```

## Arch normalization

You'll see two forms of field lists in the wild:

```python
"fields": ["name", "code"]                    # shorthand
"fields": [{"name": "name"}, {"name": "code"}]  # full form
```

Both are accepted. The framework rewrites the shorthand to the dict
form on storage so inheritance has stable addresses. You can mix
the two when authoring — write bare strings for fields you don't
need to annotate, dicts for the ones you do.

The promotion path is per-view-type:

- list views — `arch["fields"]`
- form views — `arch["sections"][*]["fields"]`
- kanban views — `arch["card"]["fields"]`, `arch["card"]["badges"]`

??? note "When to bump priority"
    Resolution order is ascending `priority`, then ascending install
    order. The default is `16` (Odoo convention). Use a higher
    number (20+ is conventional for extensions) when your patch
    must run after the base view's own attributes. You almost
    never need to think about this — sequence problems usually
    surface as install-time errors with a clear cause.
