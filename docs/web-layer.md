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

Slice A is read-only:

- `GET /api/views/{module}/{name}` → view record with parsed arch.
- `GET /api/records?model=&domain=&fields=&limit=&offset=&order=` →
  paginated rows.

`domain` is a JSON-encoded list of `[attr, op, value]` triples. Path
traversal (`country_id.region_id.name`) works exactly like the ORM
domain compiler — that's the same code.

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

## What's deliberately not here

- **Mutation endpoints** (POST/PATCH/DELETE) — Slice B.3.
- **HTMX renderer / `/web/...` HTML routes** — Slice B.2.
- **Authentication / authorization** — there's no row-level security
  yet (Stage 5). Don't expose this to the public internet.
- **`form` / `kanban` view types** — Slice B.2 brings them in
  alongside the renderer. `view_type = "list"` is the only one we
  normalize today.
- **Caching of view responses** — every request hits Postgres for the
  resolved arch. Memoizing per `(module, name)` is cheap and obvious;
  revisit when load matters.
- **Streaming / pagination metadata** — `count` is `len(recs)` from
  the current page, not the total. Add a `search_count` call if you
  need true totals.
