# Building UIs

pyvelm renders three kinds of views out of the box: **list**, **form**,
and **kanban**. You declare each one as a Python dict in a module's
data file — no Jinja, no JSX. The framework owns the templates and
dispatches every field through a widget registry to produce HTML.

A new view appears in the app as soon as you bump the module version
and reinstall. Want it linked from the sidebar? Declare an
[`ir.ui.menu` entry](modules.md#sidebar-menus) pointing at the URL.

## List views

```python
# partners/views/partner.py
from pyvelm.builders import list_view, field

VIEWS = [
    list_view(
        "partner.list", "res.partner",
        fields=["name", "code", "country_id",
                field("active", widget="toggle")],
        form_view="partner.form",            # makes rows clickable
    ),
]
```

That's enough to get a sortable, paginated, searchable table at
`/web/views/partners/partner.list`. The toolbar above the rows ships
with:

### Fixed domain

Pin a list to a subset of records with ``domain`` on the arch (ANDed
with toolbar search and filter chips — same as graph/pivot views):

```python
list_view(
    "partner.active", "res.partner",
    fields=["name", "code"],
    form_view="partner.form",
    domain=[("active", "=", True)],
)
```

Or in raw dict form: ``arch={"fields": [...], "domain": [("stage", "=", "won")]}``.

This applies to **standalone list pages** only. Embedded One2many sub-grids use
``list_view`` / ``columns`` instead — see [One2many on parent forms](one2many-forms.md).

- **Search** — single text input, ILIKE-OR across every text field
  in the view. Debounced 400 ms.
- **Filter** — drop-down builder for per-column constraints. Booleans
  get checkbox toggles; Many2one fields get a searchable picker;
  text fields get an ILIKE match.
- **Group By** — collapsible groups headed by the chosen field's
  value, with per-group counts.
- **Sort** — click a header to toggle ASC → DESC → unsorted.
- **Column reorder** — drag header cells; the order persists per
  browser via `localStorage` keyed by `(module, view_name)`.

Add a `sequence` field on the model and reference it in the arch to
turn on **row-level drag reorder**:

```python
list_view(
    "tag.list", "res.tag",
    sequence="sequence",            # field name; enables the drag handle
    fields=["name"],
)
```

The renderer adds a handle column on the left and forces sort by
`sequence ASC`. Dropping a row POSTs the new ordering to
`/web/records/{module}/{name}/reorder` and the server rewrites the
field.

### Available fields and widgets

You can write fields as bare strings or as dicts. The dict form lets
you tweak per-field attributes:

| Field type | Default render | `widget` hints |
|---|---|---|
| `Char`, `Text` | Plain text | — |
| `Integer`, `Float` | Number | — |
| `Boolean` | Coloured Yes / No pill | `"toggle"` — animated switch |
| `Many2one` | Display value with "open" link on hover | — |
| `One2many`, `Many2many` | Up to 3 chips + "+N" overflow | — |

The bare-string sugar is just shorthand for `{"name": "x"}`. Use the
dict form to add `widget`, `label`, `readonly`, or `required`.

Adding a new widget is a decorator one-liner — see [widgets](#custom-widgets)
at the end of this page.

## Form views

A form arch declares a list of layout blocks: flat **sections** and/or
tabbed **notebooks** (Odoo-style `<notebook>` / `<page>`).

Each `section(...)` has a `name`, display `title`, and `fields` list.
Each `notebook(...)` has a `name` and `pages=[page(...), ...]`; each
`page(...)` is a tab with its own `fields` grid — ideal for several
One2many sub-grids with different `list_view` values.

```python
from pyvelm.builders import form_view, section, notebook, page, field

form_view(
    "partner.form", "res.partner",
    sections=[
        section("identity", "Identity", ["name", "code"]),
        notebook("relations", pages=[
            page("children", "Contacts", ["child_ids"]),
            page("tags", "Tags", [field("tag_ids", widget="dialog")]),
        ]),
    ],
)
```

The form lives at `/web/views/{module}/{name}/record/{id}` (display
mode) and `…/edit` (edit mode). Flat sections render as stacked cards;
notebooks render a tab strip (the active tab is remembered per view in
`localStorage`). Edit mode swaps each value
for the corresponding edit-mode widget — text inputs, number
inputs, checkboxes, the [Many2one combobox](#many2one-combobox), and
the [Many2many chip editor](#many2many-chip-editor).

### Inline validation

Save fails on type errors (a letter in an Integer) or missing
required fields surface as **red borders + per-field messages on
the form itself**, with the rest of the typed values preserved.
ORM-level rejections (unique-constraint, downstream DB error) land
in a banner at the top of the form. Nothing is lost; the user just
fixes the offending field and saves again.

### Autosave on navigation

Forms in edit and new mode opt into **autosave on link clicks**: if
you've typed something into a form and then click any sidebar or
When you open a record from a list or kanban view, the breadcrumb
trail remembers where you came from (including view-switcher history:
List → Kanban → Form shows both ancestors). Search, filters, and
group-by state are restored when you click back.

breadcrumb entry, the framework saves the form first and only
follows the link on success. Cancel and Save buttons inside the
form bypass the interceptor on purpose — they own their own flows.

Browser-initiated navigation (Back button, hard reload, tab close)
falls back to the native "Leave site?" prompt — async work can't
complete on those transitions.

### Many2one combobox

Edit-mode Many2one fields render as a searchable combobox:

- **Filter as you type** against `/api/m2o/search`. Initial focus
  pre-fetches a page so the dropdown is useful before the user types.
- **Create on the fly** — if the typed text doesn't match any
  result, the dropdown shows `Create "<query>"`. Clicking creates a
  record with just `name`. If the comodel needs more required fields
  the framework redirects to the comodel's form view in `/new` mode
  ("Create and edit…").
- **Open record** — a small "↗" appears next to a selected value;
  click to jump to that comodel record's form.
- **Keyboard nav** — ↑/↓ move the cursor, Enter selects (or fires
  Create), Esc closes.

### Relational fields on forms (One2many / Many2many)

For **One2many** and **Many2many** on parent forms you choose:

1. **Edit mode** — `widget="dialog"` vs `widget="inline"` / `table`
2. **Sub-grid columns** — `columns=`, `list_view=`, or defaults
3. **Row / Add form** — `form_view=` on the field spec or model

**Full guide:** [One2many on parent forms](one2many-forms.md) (column
precedence, view ref syntax, invoice vs entry example, `FieldRef` keys).

Quick reference:

| Goal | One2many |
|------|----------|
| Reuse a list page's columns | `list_view="that.list"` on model or `field(...)` |
| Columns without any list view | `field("ids", columns=["a", "b"])` |
| Different list per parent form | `field("ids", list_view="other.list")` |
| Inline edit on parent Save | `widget="inline"` |
| Dialog edit (default) | `widget="dialog"` or omit when form exists |
| Let the user pick dialog vs inline | `edit_toggle=True` (+ `list_view` / `columns`) |

```python
section(
    "relations",
    "Relations",
    [
        field("tag_ids", widget="dialog"),
        field(
            "comment_ids",
            widget="dialog",
            edit_toggle=True,
            list_view="comment.compact",
            form_view="comment.form",
            columns=["body", "active"],
        ),
    ],
)
```

Use ``edit_toggle=True`` for a **Dialog | Inline grid** switch on one field
instead of separate tabs (see [One2many on parent forms](one2many-forms.md)).

If the comodel has **no** form view, One2many falls back to a chip
summary; Many2many falls back to inline chip search.

### Many2many — dialog mode

Selected records appear as chips. **Create new** opens the comodel
form in the dialog; **Link existing…** opens a search field to pick
records. Edit/remove use the chip actions.

### Many2many — inline mode

`widget="inline"`: removable chips plus an always-visible typeahead
input.

## Kanban views

A kanban view renders each record as a card. With `group_by`, cards
are arranged in columns (one per distinct field value) — useful for
sales pipelines, ticket boards, anything with stages. Cards can be
dragged between columns (updating the grouping field) and reordered
when the arch declares a `sequence` integer field. Without
`group_by`, cards appear in a responsive grid with the same search,
filter, group-by, and pagination toolbar as a list view (field
metadata is taken from a sibling list view when one exists).

```python
from pyvelm.builders import kanban_view, card, field

kanban_view(
    "lead.kanban", "crm.lead",
    title="Pipeline",
    card=card(
        "name",                          # field name → card heading
        subtitle="salesperson",
        fields=["partner_id", "expected_revenue"],
        badges=[field("priority"), "stage"],
    ),
    group_by="stage",                    # one column per distinct value
    sequence="sequence",                 # drag-reorder within/across columns
    form_view="lead.form",               # cards link to this form
)
```

`title` and `subtitle` are field references rendered through each
field's default display widget. `fields` is a list of label/value
pairs; `badges` are tighter chip-style indicators (typically
booleans or short collections).

When `group_by` is set, the renderer fetches every matching record
(no pagination — grouping a paginated subset is confusing UX) and
buckets them by the field's value. NULLs land in a `(no value)`
column. When `form_view` is set, each card becomes a link to
`/web/views/{module}/{form_view}/record/{id}`.

## Page titles

Each view gets a heading derived from the arch. List and kanban
views read `arch["title"]` if you set one, otherwise the model name
is humanised (`res.partner` → "Partners", `crm.lead` → "Leads",
`res.company` → "Companies"). Form views show the record's display
name (`name`, falling back to `display_name` or `#id`).

Set `title` explicitly when the default is wrong:

```python
list_view("lead.list", "crm.lead",
          title="All Leads",            # default would just be "Leads"
          fields=["name", "stage", …])
```

## Custom widgets

Register a renderer for a `(field_class, hint)` pair via the
`@widget` decorator:

```python
from pyvelm.render import widget
from pyvelm.fields import Boolean
from markupsafe import Markup

@widget(Boolean, hint="led")
def render_led(value, spec, field):
    color = "bg-green-500" if value else "bg-red-500"
    return Markup(
        f'<span class="inline-block w-3 h-3 rounded-full {color}"></span>'
    )
```

Any field that gets `widget="led"` in its arch (directly, or via
[view inheritance](inheritance.md)) renders through this function.
Register custom widgets at app startup, before `create_app()`.

A renderer's signature is `(value, field_spec, field) -> Markup`.
Returning a bare string lets Jinja auto-escape; returning `Markup`
opts out for trusted HTML — that's the safety contract.

The same registry has a parallel `mode="edit"` registry for inline-
edit controls. Display-only widgets (toggles, chips) don't
accidentally become input controls when a row enters edit mode.

## JSON over HTML

Every view is also reachable as JSON for callers that want to build
their own UI:

- `GET /api/views/{module}/{name}` returns the resolved arch
  (after [view inheritance](inheritance.md) is applied).
- `GET /api/records?model=&domain=&fields=&limit=&offset=&order=`
  returns paginated rows. `domain` is a JSON list of
  `[attr, op, value]` triples — the same compiler that powers ORM
  searches, so dotted-path traversal (`country_id.region_id.name`)
  works.

Records are serialised with the framework's conventions:

| Field type | JSON shape |
|---|---|
| Scalars (Char, Integer, Boolean, Float, Date, Text) | Pass through |
| `Many2one` | `[id, display_value]` |
| `One2many`, `Many2many` | `list[int]` of related ids |

For mutation, three endpoints round-trip JSON:

| Method | URL | Body | Returns |
|---|---|---|---|
| `POST` | `/api/records?model=…` | `{…vals}` | 201 + serialised record |
| `PATCH` | `/api/records/{id}?model=…` | `{…vals}` | 200 + serialised record after re-running stored computes |
| `DELETE` | `/api/records/{id}?model=…` | — | 204 |

All three run inside `env.transaction()`. ACL applies the same as
for HTML routes.

??? note "Where the renderer lives"
    The HTML side ships as Jinja templates in
    `pyvelm/templates/` and a widget registry in `pyvelm/render.py`.
    The CSS stack is Tailwind v4 + Flowbite, compiled by the
    `npm run build` step in the repo root and shipped as
    `pyvelm/static/dist/pyvelm.css`. Anyone consuming the rendered
    HTML can audit styling by reading the utility classes in the
    markup — there are no hand-rolled component classes.
