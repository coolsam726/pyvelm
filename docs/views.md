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

A form arch declares **sections**, each with a `name`, a display
`title`, and a `fields` list. The same string-or-dict sugar applies.

```python
from pyvelm.builders import form_view, section, field

form_view(
    "partner.form", "res.partner",
    sections=[
        section("identity", "Identity", ["name", "code"]),
        section("profile",  "Profile",
                ["age", "country_id", "parent_id",
                 field("active", widget="toggle")]),
        section("relations", "Relations", ["tag_ids", "child_ids"]),
    ],
)
```

The form lives at `/web/views/{module}/{name}/record/{id}` (display
mode) and `…/edit` (edit mode). The template renders each section as
a card with a 2-column responsive grid. Edit mode swaps each value
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

### Many2many chip editor

Edit-mode Many2many fields render selected records as removable
chips with an inline search input to add more. Search hits the same
`/api/m2o/search` endpoint. Selected ids are filtered out of the
dropdown so a record can't be added twice. Clearing every chip
posts an empty marker so the server knows the value was emptied (vs.
"not submitted").

### One2many inline table

A One2many field declared with `widget="table"` renders the child
records as a full-width table inside the parent's form section
instead of the default chip cluster:

```python
form_view("currency.form", "res.currency",
    sections=[
        section("main",  "Currency", ["code", "name", "symbol", "rounding"]),
        section("rates", "Exchange rates",
                [field("rate_ids", widget="table")]),
    ])
```

The table uses the comodel's list view fields (or every stored scalar
if no list view is installed). Each row is clickable and routes to
the comodel's form view at `/web/views/<module>/<view>/record/<id>`.
An "Add" link below the table opens the comodel's form-new endpoint
with the inverse foreign key prefilled from the parent record:

```
/web/views/<module>/<view>/new?<inverse_name>=<parent_id>
```

`/new` accepts arbitrary field-name query params and uses them as
defaults for the new record — useful any time you want to deep-link
into a partially-filled form.

Inline editing (add/edit/delete rows without leaving the parent
form) is not yet wired; clicking through to the child form is the
intended flow for now.

## Kanban views

A kanban view groups records into columns and renders each one as a
card. Useful for sales pipelines, ticket boards, anything with
stages.

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
