# Building UIs

pyvelm renders four primary record-oriented views out of the box: **list**,
**form**, **detail**, and **kanban**. You declare each one as a Python dict in a module's
data file — no Jinja, no JSX. The framework owns the templates and
dispatches every field through a widget registry to produce HTML.

**Preferred style:** assign a fluent ``views_data`` builder in each DATA file
(see [Modules → Data files](modules.md#data-files)). Legacy ``VIEWS = [list_view(...)]``
lists still load unchanged.

A new view appears in the app as soon as you bump the module version
and reinstall. Want it linked from the sidebar? Declare an
[`ir.ui.menu` entry](modules.md#sidebar-menus) pointing at the URL.

## Fluent builders

```python
# partners/views/partner.py
from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .columns(
            [
                "name",
                "code",
                "country_id",
                Field.make("active").toggle(),
            ]
        )
        .form_view("partner.form"),   # makes rows clickable
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code", "country_id", "active"]),
    )
)
```

``Field.make("name").toggle()``, ``.widget("dialog")``, ``.readonly()``,
``.columns([...])``, and similar chain on field specs inside form sections.
``ListView.make(...)``, ``FormView.make(...)``, ``DetailView.make(...)``,
``KanbanView.make(...)``,
``GraphView.make(...)``, and ``InheritView.make(...)`` cover the other view
types.

Menus belong on the same builder or a sibling DATA file:

```python
from pyvelm.builders import Menus, ViewsData

m = Menus("partners")
views_data = ViewsData.make().menus(
    m.group("business", "Business", icon="home").children([
        m.item("business.partners", "Partners").view("partner.list"),
    ]),
)
```

See ``examples/modules/partners/views/`` for a full module using fluent
declarations end to end.

## List views

The fluent list view above is enough to get a sortable, paginated, searchable table at
`/web/views/partners/partner.list`. The toolbar above the rows ships
with:

### Fixed domain

Pin a list to a subset of records with ``domain`` on the arch (ANDed
with toolbar search and filter chips — same as graph/pivot views):

```python
ListView.make("partner.active")
.model("res.partner")
.columns(["name", "code"])
.form_view("partner.form")
.domain([("active", "=", True)])
```

Or with legacy helpers: ``list_view("partner.active", "res.partner", fields=[...], domain=[...])``.
Raw dict form: ``arch={"fields": [...], "domain": [("stage", "=", "won")]}``.

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
ListView.make("tag.list")
.model("res.tag")
.columns(["name"])
.sequence("sequence")                 # field name; enables the drag handle
```

The renderer adds a handle column on the left and forces sort by
`sequence ASC`. Dropping a row POSTs the new ordering to
`/web/records/{module}/{name}/reorder` and the server rewrites the
field. Lists with a `sequence` field **disable bulk selection** (drag
reorder and checkboxes conflict).

### Bulk actions

When the user can unlink records and the list has no `sequence` field,
the toolbar shows a **bulk action bar** after you select rows: checkboxes
on each row, a select-all control in the header, and a default **Delete**
action.

Declare custom actions on the list arch:

```python
ListView.make("partner.list")
.model("res.partner")
.columns(["name", "code"])
.bulk_actions([
    {
        "action": "unlink",
        "label": "Delete",
        "confirm": "Delete selected partners?",
        "perm": "unlink",
    },
])
```

The browser POSTs `{action, ids}` to
`/web/records/{module}/{name}/bulk`. Built-in actions today: `unlink`.
Omit `bulk_actions` to keep the default delete-only bar when unlink is
allowed.

### Detail views and row actions

Use a **detail view** for read-only record pages separate from the edit
form. Row clicks open the detail view when the user has read access.

```python
from pyvelm.builders import DetailView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .columns(["name", "code"])
        .detail_view("partner.detail"),
        DetailView.make("partner.detail")
        .model("res.partner")
        .form_view("partner.form")   # Edit button target
        .section("identity", "Identity", ["name", "code", "country_id"]),
    )
)
```

Detail views live at `/web/views/{module}/{name}/record/{id}` (same URL
shape as forms). Set `form_view` on the detail arch so the **Edit** button
opens the paired form in edit mode.

Per-row toolbar buttons (resolved like form header actions):

```python
ListView.make("partner.list")
.model("res.partner")
.columns(["name"])
.row_actions([
    {"label": "Mail", "method": "POST", "url": "/web/actions/..."},
])
```

If `detail_view` is omitted, the list falls back to the first detail view
registered for the same model, then to `form_view`.

### Available fields and widgets

You can write fields as bare strings or as dicts. The dict form lets
you tweak per-field attributes:

| Field type | Default render | `widget` hints |
|---|---|---|
| `Char`, `Text` | Plain text | — |
| `Integer`, `Float` | Number | — |
| `Boolean` | Coloured Yes / No pill | `"toggle"` — animated switch |
| `Many2one` | Display value + separate **open** button (dialog) | — |
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
from pyvelm.builders import Field, FormView, Notebook, Page, ViewsData

views_data = (
    ViewsData.make()
    .views(
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code"])
        .notebook(
            "relations",
            "Relations",
            [
                Page.make("children", "Contacts").fields(["child_ids"]),
                Page.make("tags", "Tags").fields(
                    [Field.make("tag_ids").widget("dialog")]
                ),
            ],
        ),
    )
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

Forms in **edit** and **new** mode opt into **autosave on link clicks**:
if you've changed the form and then click a normal in-app link (sidebar,
breadcrumb, menu), the framework **POSTs the form first** and only follows
the link when that save succeeds. **Save**, **Cancel**, and **Ctrl+S**
bypass this interceptor.

Browser-initiated navigation (Back, reload, tab close) cannot finish async
work; a dirty form triggers the native **Leave site?** prompt instead.

When you open a record from a list or kanban, breadcrumbs remember where you
came from (including List → Kanban → Form). Search, filters, and group-by
are restored when you go back.

### Sticky actions, Ctrl+S, and save toasts

See **[Form UX](form-ux.md)** for:

- **Sticky** Edit / Save / Cancel bar while scrolling long forms
- **Ctrl+S** / **Cmd+S** to save
- **Success toasts** after Save / Create
- Opening related records in **`PvDialog`** (Many2one open button, O2M rows)

### Many2one combobox

Edit-mode Many2one fields render as a searchable combobox:

- **Filter as you type** against `/api/m2o/search`. Initial focus
  pre-fetches a page so the dropdown is useful before the user types.
- **Create on the fly** — if the typed text doesn't match any
  result, the dropdown shows `Create "<query>"`. Clicking creates a
  record with just `name`. If the comodel needs more required fields
  the framework redirects to the comodel's form view in `/new` mode
  ("Create and edit…").
- **Open record** — a small **↗** button beside the selected value opens
  the comodel form in **`PvDialog`** (not full-page navigation). Use
  **Open full page** in the dialog title when you need the normal route.
- **Keyboard nav** — ↑/↓ move the cursor, Enter selects (or fires
  Create), Esc closes.

### Relational fields on forms (One2many / Many2many)

<a id="relational-fields-on-forms-on2many--many2many"></a>

For **One2many** and **Many2many** on parent forms you choose:

1. **Edit mode** — `widget="dialog"` vs `widget="inline"` / `table`
2. **Sub-grid columns** — `columns=`, `list_view=`, or defaults
3. **Row / Add form** — `form_view=` on the field spec or model

**Full guide:** [One2many on parent forms](one2many-forms.md) (column
precedence, view ref syntax, invoice vs entry example, `FieldRef` keys).

Quick reference:

### Relational fields: `widget="dialog"` vs `widget="inline"`

<a id="relational-fields-widgetdialog-vs-widgetinline"></a>

| Goal | One2many |
|------|----------|
| Reuse a list page's columns | `list_view="that.list"` on model or `field(...)` |
| Columns without any list view | `field("ids", columns=["a", "b"])` |
| Different list per parent form | `field("ids", list_view="other.list")` |
| Inline edit on parent Save | `widget="inline"` |
| Dialog edit (default) | `widget="dialog"` or omit when form exists |
| Let the user pick dialog vs inline | `edit_toggle=True` (+ `list_view` / `columns`) |

```python
FormView.make("note.form")
.model("my.note")
.section(
    "relations",
    "Relations",
    [
        Field.make("tag_ids").widget("dialog"),
        Field.make("comment_ids")
        .widget("dialog")
        .edit_toggle()
        .list_view("comment.compact")
        .form_view("comment.form")
        .columns(["body", "active"]),
    ],
)
```

Use ``edit_toggle=True`` for a **Dialog | Inline grid** switch on one field
instead of separate tabs (see [One2many on parent forms](one2many-forms.md)).

If the comodel has **no** form view, One2many falls back to a chip
summary; Many2many falls back to inline chip search.

### Many2many — dialog mode

<a id="many2many-chip-editor"></a>

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
from pyvelm.builders import Field, KanbanCard, KanbanView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        KanbanView.make("lead.kanban")
        .model("crm.lead")
        .title("Pipeline")
        .card(
            KanbanCard.make()
            .title("name")
            .subtitle("salesperson")
            .fields(["partner_id", "expected_revenue"])
            .badges([Field.make("priority"), "stage"])
        )
        .group_by("stage")
        .sequence("sequence")
        .form_view("lead.form"),
    )
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
ListView.make("lead.list")
.model("crm.lead")
.title("All Leads")                     # default would just be "Leads"
.columns(["name", "stage", …])
```

## Legacy function helpers

The original function API remains available and delegates to the same fluent
classes:

```python
from pyvelm.builders import field, form_view, list_view, section

VIEWS = [
    list_view(
        "partner.list", "res.partner",
        fields=["name", field("active", widget="toggle")],
        form_view="partner.form",
    ),
    form_view(
        "partner.form", "res.partner",
        sections=[section("identity", "Identity", ["name", "code"])],
    ),
]
```

``field("x", widget="toggle")`` and ``Field.make("x").toggle()`` are equivalent.
New scaffolds and bundled modules use the fluent style; migrate when convenient.

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
