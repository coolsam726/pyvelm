# Web layer & views as data

Stage 4 Slice A: views live as records, and a thin FastAPI app exposes
read endpoints over them. The intent is to let a frontend (web or
otherwise) render generic UIs without each model needing a bespoke
controller.

## Views as records

The `ir.ui.view` model (shipped here in `examples/modules/base/`)
stores the declarative definition of a view:

| field      | meaning                                              |
|------------|------------------------------------------------------|
| `module`   | owning module (used together with `name` for upserts)|
| `name`     | logical name within the module (e.g. `partner.list`) |
| `model`    | model the view is for                                |
| `view_type`| `"list"` (Slice A). `"form"` and `"kanban"` later    |
| `arch`     | type-specific JSON-encoded layout                    |

Identity is `(module, name)`. The loader upserts on every install pass,
so re-declaring an existing view in a manifest just overwrites the
previous arch. There is no separate "view migration" — you change the
declaration, bump the module version, and the next install picks it up.

## Declaring views

Views live in Python files under the module, listed in the manifest's
`DATA` key (see [module-loading.md](module-loading.md#data-files)):

```python
# partners/__pyvelm__.py
NAME = "partners"
VERSION = (0, 2, 0)
DEPENDS = ["base"]
DATA = ["views/partner.py"]
```

```python
# partners/views/partner.py
VIEWS = [
    {
        "name": "partner.list",
        "model": "res.partner",
        "view_type": "list",
        # Authoring sugar: bare strings get normalized to {"name": str}
        # at load time so inheritance can address them.
        "arch": {"fields": ["name", "code", "age", "country_id", "active"]},
        "priority": 16,            # optional, default 16 (Odoo convention)
    },
]
```

The loader validates required keys (`name`, `model`, `view_type`,
`arch`) and raises early on omissions. The stored arch in
`ir.ui.view.arch` is the normalized form — the list of strings becomes
a list of `{"name": ...}` dicts. This is what extensions address
against.

If `ir.ui.view` isn't loaded (e.g. you skipped the base module), `VIEWS`
declarations are quietly ignored. This lets you bring up a base-only
install without pulling in the view machinery.

## View inheritance

A downstream module patches an upstream view via `VIEW_INHERITS`,
declared in a file the manifest references through `DATA`:

```python
# partners_pro/__pyvelm__.py
NAME = "partners_pro"
VERSION = (0, 1, 0)
DEPENDS = ["partners"]
DATA = ["views/partner.py"]
```

```python
# partners_pro/views/partner.py
VIEW_INHERITS = [
    {
        "name": "partner.list.pro",
        "inherit": "partners.partner.list",     # parent ref: module.name
        "priority": 20,                          # default 16
        "operations": [
            {"op": "remove",  "target": ["fields", "age"]},
            {"op": "after",   "target": ["fields", "country_id"],
                              "value": {"name": "tag_ids"}},
            {"op": "replace", "target": ["fields", "active"],
                              "value": {"name": "active", "widget": "toggle"}},
        ],
    },
]
```

`/api/views/{module}/{name}` always returns the **resolved** arch —
the base view with every extension's operations applied in ascending
`priority` order (ties broken by install order). You get the same
answer whether you address the base or the extension. Extension views
exist primarily as records the loader manages; they don't have their
own arch.

### Operations

Six op kinds, all with the same `target` shape (a list of keys into
the normalized arch):

| op | parent must be | effect |
|----|----------------|--------|
| `set` | dict or list | write `value` at the target position; on a dict, the final key may be new (adds an attribute) |
| `replace` | same as `set` | alias of `set`, reads better in list contexts |
| `update` | the target itself, a dict | `dict.update(value)` — merge attributes in one op |
| `remove` | dict or list | delete the target |
| `before` | list | insert `value` immediately before the target index |
| `after`  | list | insert `value` immediately after the target index |

`update` is the Odoo `position="attributes"` equivalent: terse when
you have several attributes to set on the same field. For a single
attribute, `set` with a leaf-key target reads naturally.

```python
# Two equivalent ways to set widget="toggle" on `active`:
{"op": "set",    "target": ["fields", "active", "widget"], "value": "toggle"},
{"op": "update", "target": ["fields", "active"],           "value": {"widget": "toggle"}},

# `update` shines when there's more than one attribute:
{"op": "update", "target": ["fields", "active"],
 "value": {"widget": "toggle", "readonly": True, "label": "Active?"}},

# Removing an attribute mirrors the set form:
{"op": "remove", "target": ["fields", "active", "readonly"]},
```

### Target resolution

A `target` is a list of segments. Each segment is matched against the
node it walked into:

| segment type | parent type | match rule |
|--------------|-------------|------------|
| `str` | dict | key lookup |
| `str` | list of dicts | match by the entry's `name` field |
| `int` | list | positional index |

So `["fields", "active"]` reaches the field-dict whose `name` is
`"active"` inside the `fields` list. Errors at any segment raise during
install — there's no silent skip.

### Arch normalization

The framework defines per-`view_type` "promotion paths": list positions
where bare strings are sugar for `{"name": "<str>"}`. Today:

- `list` views: `arch["fields"]`

Form and kanban view normalizers come with their view types. The rule
of thumb when designing a new view_type: every list position whose
entries are "named addressable things" should be promotable.

## The HTTP app

`pyvelm.web.create_app(registry, pool)` builds a FastAPI app bound to a
loaded `Registry` and a psycopg connection pool. Each request checks
out a connection from the pool, wraps it in a fresh `Environment`, and
returns it to the pool on exit.

```python
from psycopg_pool import ConnectionPool
from pyvelm.web import create_app

pool = ConnectionPool(dsn, min_size=1, max_size=10, open=True)
app = create_app(registry, pool)
# Hand `app` to uvicorn / gunicorn / your favorite ASGI server.
```

Read endpoints:

- `GET /api/views/{module}/{name}` → view record with parsed arch
  (post-inheritance).
- `GET /api/records?model=&domain=&fields=&limit=&offset=&order=` →
  paginated rows.

`domain` is a JSON-encoded list of `[attr, op, value]` triples. Path
traversal (`country_id.region_id.name`) works exactly like the ORM
domain compiler — that's the same code.

Mutation endpoints (Slice B.3):

- `POST   /api/records?model=...` — body is a JSON vals dict;
  returns the serialized created record. 201 on success.
- `PATCH  /api/records/{id}?model=...` — body is a JSON vals dict;
  applies a partial update and returns the serialized record after
  any stored compute fields have re-run. 200 on success.
- `DELETE /api/records/{id}?model=...` — 204 on success.

All three run inside `env.transaction()`, so partial failures leave
nothing behind. Unknown fields raise 400; unknown records raise 404.
There is **no authentication or authorization layer** — Stage 5's
record rules are what'll guard write endpoints. Until then, don't
expose this to the public internet.

## JSON serialization

`pyvelm.web.serialize_record(record, fields=None)` is the canonical
shape converter:

- Scalars (Char, Integer, Boolean, Float, Date, Text) pass through.
- `Many2one` → `[id, display_value]`. `display_value` tries
  `display_name` (Odoo convention) then `name`, then `str(id)`.
- `One2many` / `Many2many` → `list[int]` of related ids. Frontend can
  fetch details from `/api/records` keyed by that.
- `id` is always included.

Unknown fields raise `HTTPException(400)`. Use `?fields=` to project,
otherwise every stored field comes back.

## Why a separate pool

The framework runs the ORM synchronously; FastAPI's async layer wraps
each request in its own connection. Sharing a single connection across
requests under autocommit can mostly work but races on transaction
state when `env.transaction()` enters the picture. A pool with
`min_size>=1` removes that class of bug for the cost of one extra
dependency.

For tests, a `min_size=1, max_size=2` pool is fine. Real deployments
should size against expected concurrency; that's a deployment concern,
not a framework one.

## HTMX + Jinja renderer

Default UI shipped with the framework. Developers don't write Jinja:
the framework owns the templates and dispatches each field through a
widget registry to produce HTML.

**CSS stack: Tailwind v4 + Flowbite, built locally.** This is the
major UI-stack deviation from Odoo (which ships Bootstrap). The build
config lives at the repo root:

- `package.json` declares `tailwindcss@^4.1`, `@tailwindcss/cli`, and
  `flowbite@^3.1`.
- `pyvelm/static/tailwind.css` is the entry point — `@import
  "tailwindcss";`, `@plugin "flowbite/plugin";`, `@source` lines that
  scan templates and `pyvelm/render.py`, and `@theme` blocks declaring
  the framework's color tokens (brand / success / danger / warning,
  plus neutral surface tokens with light/dark variants).
- `pyvelm/static/pyvelm.css` is included from there and carries the
  semantic-token mapping (`--color-fg-brand`, `--color-neutral-primary`,
  etc.) plus the `.dark` overrides.
- `npm run build` (or `npm run dev` for watch) compiles to
  `pyvelm/static/dist/pyvelm.css`. The same script also copies
  `flowbite.min.js` into the dist folder so a single static mount
  serves both.
- The dist directory is checked into git so the Python smoke test
  runs out of the box. `node_modules/` is gitignored.

The compiled CSS is served via the existing `/web/static` mount
(`pyvelm/templates/layouts/main.html` links `/web/static/dist/pyvelm.css`).

**Page-heading region.** The layout draws a single header strip per
page: optional breadcrumb on top, an `h2` title + optional subtitle
below, page actions on the right. Pages just set:

- `{% block page_title %}` — the title text (also used by the
  compact h1 in the topbar).
- `subtitle` — a string passed from the renderer (e.g. "res.partner
  · 3 records").
- `{% block page_actions %}` — buttons on the right.

For custom heading layouts, override `{% block page_heading %}`
directly (replaces the title+subtitle markup, keeps the breadcrumb /
actions row). The breadcrumb derives from the menu tree via
`render.build_breadcrumbs(menu, current_path, leaf_label)`; renderers
can pass a `leaf_label` to override the trailing crumb (form views
use the record's display name).

**Layout shell.** `pyvelm/templates/layouts/main.html` is the base
template every page extends. It provides:

- A persistent sidebar with a multi-level navigation tree driven by
  the `ir.ui.menu` model. Each module contributes entries via a
  `MENUS` list in one of its data files; the loader upserts them
  keyed by `(module, name)` the same way it handles views.
  `render._menu(env, current_path)` reads the table at render time
  and emits the two-level tree the template renders. Parents are
  referenced by `"<module>.<name>"`; `sequence` orders siblings.
- A topbar with the page title, company switcher (Flowbite-style
  dropdown), theme toggle, and user menu.
- A `class="dark"`/light theme toggle that persists in `localStorage`
  and pre-applies before paint to avoid FOUC.
- An Alpine.js-driven dialog component (`window.pvConfirm`,
  `window.pvAlert`) for confirm/alert flows; the in-template event
  bus is `pv-confirm-request` / `pv-alert-request`.

The shell expects a stable bundle of variables (`menu`,
`current_user_name`, `companies`, `current_company_id`, etc.).
`render.layout_context(env, current_path)` builds that bundle; every
page renderer (`render_list_page`, `render_form_page`,
`render_kanban_page`, `render_admin_page`) calls it.

**Routes**

Page + pagination:
- `GET /web/views/{module}/{name}?page=&page_size=` — full HTML page.
  Header, the table shell, the first page of rows, "+ New" button, and
  a "Load more" button when there are more rows.
- `GET /web/records/{module}/{name}?page=&page_size=` — `<tr>` fragment
  for HTMX `hx-swap="beforeend"`. Also returns an out-of-band swap of
  the load-more button when there are still more rows beyond this page.

Form view (single record):
- `GET    /web/views/{m}/{n}/record/{id}` — display form (full page;
  if `HX-Request: true` header is set, body fragment only for in-place
  HTMX swap).
- `GET    /web/views/{m}/{n}/record/{id}/edit` — edit form (same
  HX-Request fragment convention).
- `POST   /web/views/{m}/{n}/record/{id}` — form-encoded body; save
  and return display form.
- `GET    /web/views/{m}/{n}/new` — empty edit form for a new record.
- `POST   /web/views/{m}/{n}` — create from form-encoded body; returns
  the display form for the newly-created record.
- Delete is routed through the JSON API (`DELETE /api/records/{id}`)
  from the form's Delete button.

Inline edit (per-row):
- `GET    /web/records/{m}/{n}/row/{id}/edit` — `<tr>` with input
  controls. Save / Cancel buttons in the Actions column.
- `GET    /web/records/{m}/{n}/row/{id}` — display `<tr>` (used by
  Cancel to revert without round-tripping the form state).
- `POST   /web/records/{m}/{n}/row/{id}` — form-encoded body; applies
  write and returns the updated display `<tr>`.
- `DELETE /web/records/{m}/{n}/row/{id}` — unlinks; returns empty body
  so `hx-swap="outerHTML"` removes the row.
- `GET    /web/records/{m}/{n}/new` — empty edit `<tr>` for inline
  creation. Append to the top of the table via `hx-swap="afterbegin"`.
- `POST   /web/records/{m}/{n}` — form-encoded body; creates and
  returns the new display `<tr>`.

Static:
- `GET /web/static/...` — bundled static directory, presently
  containing only a placeholder. App developers can ship their own
  assets by overriding the static mount when they call `create_app`.

**Widget registry** (`pyvelm.render`)

The dispatch key is `(field_class, hint)`. The hint comes from the
`widget` attribute on a field-spec dict in the arch — set or modified
by inheritance ops, never hand-edited in Jinja.

| Field type | No hint | Hint |
|---|---|---|
| `Char` / `Text` | escape-and-print | (extensible) |
| `Integer` / `Float` | escape-and-print | |
| `Boolean` | check / cross | `"toggle"` → styled toggle |
| `Many2one` | display value (`display_name` → `name` → id) | |
| `One2many` / `Many2many` | up to 3 chips + "+N" overflow | |

A renderer is `(value, field_spec, field) -> Markup`. Returning a bare
string lets Jinja auto-escape; returning `markupsafe.Markup(...)` opts
out for raw HTML — used by toggle, chips, etc. That's the safety
contract.

**Widgets emit Tailwind utility classes.** No hand-rolled component
classes by default; just utilities directly on the elements. This
keeps the framework's CSS surface essentially zero — anyone consuming
the rendered HTML can audit styling by reading the markup.

**Two modes, one registry.** Each widget can register either a
`display` renderer (default) or an `edit` renderer (used when a row
enters inline-edit). The lookup mirrors display: `(field_class, hint,
mode)` with MRO + hint fallback. Built-in edit widgets:

| Field type | Edit-mode control |
|---|---|
| `Char` / `Text` | `<input type="text">` |
| `Integer` | `<input type="number" step="1">` |
| `Float` | `<input type="number" step="any">` |
| `Boolean` (and `+toggle`) | `<input type="checkbox">` with a paired hidden `""` so unchecked submits as false |
| `Many2one` | searchable combobox with create-on-the-fly + open-record link (`widgets/m2o_input.html`, `pvM2o` Alpine component) |
| `One2many` / `Many2many` | display rendering (no multi-select widget yet) |

The Boolean trick — a hidden `name="x" value=""` immediately before
the checkbox — is necessary because unchecked checkboxes don't submit
at all. The hidden field guarantees the key is present; if checked,
the checkbox's `value="on"` is the last value and wins under
`getlist(...)`.

`parse_form_vals(model_cls, form_data)` is the inverse: it coerces
strings back to Python types using the model's field metadata
(int/float casting, `""` → `None`, Many2one ids as ints). Unknown
keys are ignored so form-private fields can't bleed into vals.

Adding a widget is a decorator one-liner:

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

Then any field that gets a `widget: "led"` hint (via inheritance or
directly in arch) renders through it. Apps that need custom widgets
register them at startup before `create_app`.

**View arch in JSON, HTML in the renderer.** Apps that want a SPA
ignore `/web/*` and consume `/api/*`. Apps that want the default UI
ignore `/api/*`. They share the same `ir.ui.view.arch` and the same
inheritance resolution.

## Form views

A `form` view declares `sections`, each with a stable `name`, a
display `title`, and a `fields` list. The same string-or-dict
authoring sugar applies (`"fields": ["name", "code"]` is fine for
the common case; expand to `{"name": ..., "widget": ...}` when
you need per-field attributes).

Inheritance reaches into sections via deeper paths:
`["sections", "profile", "fields", "active"]` addresses the
`active` field inside the section named `profile`. All six op kinds
(`set`/`replace`/`update`/`remove`/`before`/`after`) work the same
way they do for list views.

```python
# partners/views/partner.py
VIEWS = [
    {
        "name": "partner.form",
        "model": "res.partner",
        "view_type": "form",
        "arch": {
            "sections": [
                {"name": "identity",  "title": "Identity",
                 "fields": ["name", "code"]},
                {"name": "profile",   "title": "Profile",
                 "fields": ["age", "country_id", "parent_id", "active"]},
                {"name": "relations", "title": "Relations",
                 "fields": ["tag_ids", "child_ids"]},
            ],
        },
    },
]
```

```python
# partners_pro/views/partner.py — section-level inheritance
VIEW_INHERITS = [
    {
        "name": "partner.form.pro",
        "inherit": "partners.partner.form",
        "priority": 20,
        "operations": [
            {"op": "set",
             "target": ["sections", "profile", "title"],
             "value": "Demographics"},
            {"op": "update",
             "target": ["sections", "profile", "fields", "active"],
             "value": {"widget": "toggle"}},
            {"op": "remove",
             "target": ["sections", "profile", "fields", "parent_id"]},
        ],
    },
]
```

The form template renders each section as a Tailwind-styled card
with a `<legend>` and a responsive 2-column grid of label / value
pairs. Display mode shows each value through the display-mode widget
registry; edit mode swaps in the edit-mode widgets (text inputs,
selects, etc.). HTMX swaps target `#pyvelm-form-shell` so the action
buttons (Edit / Save / Cancel / Delete) repaint correctly when modes
change.

For direct navigation, the routes return a full HTML page. For
in-place HTMX swaps, the same routes detect the `HX-Request: true`
header and return only the body fragment.

**Autosave on navigation.** Edit and New forms render with
`data-pv-autosave="<save-url>"` on the `<form>`. A layout-level
script in `layouts/main.html` snapshots the form's `FormData` at
mount and after every `htmx:afterSwap`, marks the form dirty as the
user types, and intercepts left-click navigation on `a[href]`
elements anywhere in the page: if the form is dirty when the user
clicks a sidebar entry, breadcrumb, or any other link, the
interceptor POSTs to the autosave URL first and only follows the
link on success. Save failures surface through `window.pvAlert` and
keep the user on the form. For browser-initiated navigation (Back,
Close, hard reload) we fall back to the native `beforeunload`
prompt — async work can't complete on those transitions. Cancel
and Save buttons inside the form bypass the interceptor on purpose
because they own their own swap semantics.

## Kanban views

A `kanban` view renders records as cards, optionally grouped into
columns. Arch shape:

```python
{
    "name": "partner.kanban",
    "model": "res.partner",
    "view_type": "kanban",
    "arch": {
        "card": {
            "title": "name",                # field name (string)
            "subtitle": "code",
            "fields": ["age", "country_id"],
            "badges": [
                {"name": "active", "widget": "toggle"},
                "tag_ids",
            ],
        },
        "group_by": "country_id",          # optional
        "form_view": "partner.form",       # optional, makes cards clickable
    },
}
```

`title` and `subtitle` are single-field references rendered through
the field's default display widget. `fields` is a list of fields with
labels; `badges` are tighter chip-style indicators (typically
booleans, short collections). Strings in `fields` and `badges` are
promoted to `{"name": str}` on storage, same as list / form views.

When `group_by` is set, the renderer groups all records by that
field's value (Many2one buckets by id with display-value column
header; scalar buckets by raw value). Records whose value is null
land in a `(no value)` column.

When `form_view` is set, each card becomes an anchor linking to
`/web/views/{module}/{form_view}/record/{id}`. Without `form_view`,
cards are plain divs.

The route at `GET /web/views/{module}/{name}` dispatches by
`view_type`:
- `list` → `render_list_page`
- `kanban` → `render_kanban_page`
- `form` → 501 (form views live at `.../record/{id}`)

Inheritance addresses card fields by name the same way list views
do — `["card", "fields", "country_id"]` reaches the dict with
`name="country_id"` in the card's fields list. Card-level keys
(title, subtitle, group_by, form_view) are addressed via simple
`set`/`remove` ops at the top of the arch.

## What's deliberately not here

- **Authentication / authorization** — there's no row-level security
  yet (Stage 5). Don't expose mutation endpoints to the public internet.
- **Many2many / One2many editing widgets** — the edit-mode renderer
  for these falls through to the display rendering. A real multi-
  select needs design (chip removal, search-add, etc.).

## Data tables

List views render a server-side DataTable with:

- **Pagination** — page-numbered (`list_pagination.html`); page
  size selector with 10/20/50/100. URL-bookmarkable via
  `?search=&order=&filters=&page=&page_size=`.
- **Search** — single text box, ILIKE-OR across every text field in
  the resolved arch. Debounced 400ms.
- **Per-column filters** — a small input under each header.
  Type-aware: text fields go through ILIKE, Many2one tries an id
  match first then falls back to `<m2o>.name ILIKE`. Filters AND
  together. Persisted in the URL alongside search.
- **Per-column sort** — click a header to toggle
  ASC → DESC → unsorted.
- **Column reorder** — drag-and-drop column headers. The chosen
  order is persisted to `localStorage` keyed by
  `(module, view_name)` and re-applied after every HTMX swap by the
  `pvList` Alpine component. The Actions column always stays last.

Row-level reorder via a drag handle (the Odoo "handle" widget for
ordered records via a `sequence` field) is **not** shipped yet —
it'd need a model-level `sequence` integer and a different DnD
target. Deferred.

All four features live in `pvList` (Alpine component in `list.html`)
plus `_parse_filters` and `_build_search_domain` in
`pyvelm/render.py`. The server endpoint
`GET /web/records/{module}/{name}` accepts `search`, `order`,
`filters` (JSON dict), `page`, `page_size` and returns the
re-rendered table fragment; HTMX swaps it into
`#pv-table-container`.

## Many2one combobox

Edit-mode Many2one fields render as a searchable combobox modelled
after Odoo's classic m2o widget:

- **Filter-as-you-type** against `GET /api/m2o/search?model=&q=&limit=`.
  The endpoint ILIKE-matches the comodel's `name` field (or the first
  stored Char/Text it can find) and returns `{results: [{id, label}, ...]}`.
  Initial focus fetches the first page so the dropdown is useful even
  before the user types.
- **Create on the fly**: when the typed text doesn't exactly match any
  result, the dropdown offers a `Create "<query>"` entry. Clicking
  posts to `POST /api/m2o/quick-create` `{model, name}`. The endpoint
  returns 400 with the list of missing required fields when the
  comodel needs more than `name` — the client then falls back to
  `Create and edit…` which navigates to the comodel's form view's
  `/new` page.
- **Open record**: when a value is selected and a form view exists for
  the comodel, a small "↗" icon appears next to the input and links to
  `/web/views/<module>/<form_view>/record/<id>`. The display-mode
  Many2one widget shows the same affordance inline on hover.
- **Keyboard nav**: ↑ ↓ move the cursor in the dropdown; Enter selects
  (or triggers Create when the cursor is on the create entry); Esc
  closes and restores the visible text to the last-selected label.

The widget partial is `pyvelm/templates/widgets/m2o_input.html`. The
Alpine component `pvM2o` lives in `layouts/main.html`'s global init
block so any page that renders the partial picks it up. Per-record
form-view URLs are stashed on the field-spec by
`_enrich_specs_for_edit` so the widget never has to look them up at
request time — the spec is enriched once per render.
- **Field-level validation feedback in the inline-edit form** — today
  invalid input raises and HTMX won't swap. The intended UX is to
  return the edit fragment with inline error messages on 422; that
  needs a small `errors` plumbing layer in the renderer.
- **Caching of view responses** — every request hits Postgres for the
  resolved arch. Memoizing per `(module, name)` is cheap and obvious;
  revisit when load matters.
- **Streaming / pagination metadata** — `count` is `total` from
  `search_count`; rows are paginated by `limit/offset`. No cursor
  abstraction yet.
