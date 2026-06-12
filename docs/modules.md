# Modules

A pyvelm **module** is a Python package on disk that ships some
combination of models, views, and seed data. Modules are the unit of
install, upgrade, and uninstall — they're how you ship your code as
a self-contained piece other apps can depend on or extend.

## When to read this page

Use this guide after [Getting started](getting-started.md) and your first
generated module. It explains the structure you will maintain long-term:

1. Manifest and dependency metadata
2. Data files (`views_data`) and menus
3. Install/upgrade lifecycle, migrations, and seeders

## Shape on disk

```
mymodule/
├── __init__.py          # can be empty
├── __pyvelm__.py        # manifest = Manifest.make("mymodule")…
├── models/
│   ├── __init__.py      # imports every model file
│   └── partner.py
├── views/
│   ├── __init__.py
│   ├── partner.py       # views_data = ViewsData.make()…
│   └── menu.py          # menus on views_data or Menus builder
├── commands/            # optional Artisan CLI commands
└── migrations/          # optional
    ├── __init__.py
    └── 0_1_to_0_2.py
```

`pyvelm make:module` / `pyvelm new` create an **empty** shell (no `.data(...)` yet).
Use `make:model`, `make:view`, and `make:menu` to add each layer — see
[Console commands](console.md).

## The manifest

`__pyvelm__.py` is plain Python. Assign a fluent builder to
``manifest`` (velmphp-style):

```python
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("partners")
    .version(0, 1, 0)
    .depends("base")
    .data("views/partner.py", "views/tag.py")
    .install_hook("partners.hooks:install")
    .summary("Companies, contacts, and the partner directory.")
    .category("Business")
)
```

Legacy module-level constants remain supported for older addons:

```python
NAME: str = "partners"
VERSION: tuple[int, ...] = (0, 1, 0)
DEPENDS: list[str] = ["base"]
DATA: list[str] = ["views/partner.py", "views/tag.py"]
INSTALL_HOOK: str = "partners.hooks:install"
```

``.depends(...)`` / `DEPENDS` is what the loader uses to topologically order installs;
``.data(...)`` / `DATA` lists Python files whose ``views_data`` builder (or legacy
`VIEWS`, `VIEW_INHERITS`, `MENUS`) feed the declarative-data sync; `INSTALL_HOOK` is a
`pkg.mod:fn` reference to a function called once on first install (it
gets the `Environment`).

Optional **`.web_routes("pkg.web:register_routes")`** registers
module-owned FastAPI endpoints when `create_app()` starts — no edits to
`serve.py`. See [Custom HTTP routes](#custom-http-routes) below.

`pyvelm.Manifest` is the fluent builder class; `pyvelm.types.Manifest`
is a TypedDict documenting every recognised key for type checkers.

For **model and view technical names** (`env["res.partner"]`,
`view="lead.list"`), run [`pyvelm make:stubs`](ide-typing.md) to
generate `Literal` unions and checker config — see
[IDE typing stubs](ide-typing.md).

### Catalog metadata

These optional keys drive the **Apps catalog** UI (more below).
Modules without them appear as "Uncategorised" with a blank
summary — purely informational, no impact on install behaviour.

```python
SUMMARY: str = "Sales pipeline, leads, and opportunity tracking."
DESCRIPTION: str = "Longer prose. Markdown-ish."
CATEGORY: str = "Business"           # groups cards on /web/apps
AUTHOR: str = "Your Team"
ICON: str = "<svg ...>...</svg>"      # raw inline SVG; rendered as-is
```

## Models

Each module's models live in a Python package the manifest points
at — `models/` by default, override via `MODELS_PACKAGE`.

```python
# partners/models/__init__.py
from . import partner          # noqa: F401
from . import tag              # noqa: F401
```

```python
# partners/models/partner.py
from pyvelm import Char, Integer, Many2one, models


class Partner(models.Model):
    _name = "res.partner"
    name = Char(required=True)
    age = Integer()
    country_id = Many2one("res.country", ondelete="SET NULL")
```

The framework creates the table on first install and `ALTER TABLE
ADD COLUMN`s any new field declarations on subsequent upgrades.
See [Declaring models](models.md) for the field reference.

## Data files

Anything declarative — views, view extensions, sidebar menu
entries — lives in Python files referenced by `DATA`:

```python
# partners/__pyvelm__.py
manifest = Manifest.make("partners").data("views/partner.py", "views/menu.py")
```

The loader executes each file and harvests declarative data from a
fluent ``views_data`` builder (preferred) or legacy module-level lists
(``VIEWS``, ``VIEW_INHERITS``, ``MENUS``).

```python
# partners/views/partner.py
from pyvelm.builders import Field, FormView, ListView, ViewsData

views_data = (
    ViewsData.make()
    .views(
        ListView.make("partner.list")
        .model("res.partner")
        .columns(["name", "code", "country_id"])
        .form_view("partner.form"),
        FormView.make("partner.form")
        .model("res.partner")
        .section("identity", "Identity", ["name", "code"])
        .section("location", "Location", ["country_id"]),
    )
)
```

Legacy function helpers (``list_view``, ``form_view``, ``field``, …) remain
available and produce the same dicts the loader always consumed.

Files that don't define any of those lists are still imported — use
this for side-effects like registering custom widgets via
`@pyvelm.render.widget`.

## Sidebar menus

A `MENUS` list contributes entries to `ir.ui.menu`, which drives the
signed-in shell. By default the UI uses the **apps** layout (applications
in the left rail, pages in the top bar); set `PYVELM_MENU_LAYOUT=sidebar`
for a three-level nested sidebar. See **[Navigation](navigation.md)**
for layout modes, depth, and template context.

Structure menus in **three levels** when using the default `apps` layout:

| Level | Role | Example |
|-------|------|---------|
| 1 | Application (sidebar rail) | `Settings`, `CRM` |
| 2 | Subsection (top bar tab or dropdown) | `Users & access`, `Pipeline` |
| 3 | Page (link or dropdown item) | `Users`, `All Leads` |

Keep level 2 sparse (a handful of subsections per app); put list/form
routes at level 3. See **[Navigation](navigation.md)** for layout detail.

Top-level **groups** have an optional `icon` and no `href`. Nested
**groups** use `parent=`; **leaf items** link to a view or URL.

Use the **`Menus`** builder so you only pass names you already know from
`VIEWS` — not hand-built `/web/views/...` paths:

```python
# partners/views/menu.py  —  module name in __pyvelm__.py is "partners"
from pyvelm.builders import Menus, ViewsData

m = Menus("partners")

views_data = ViewsData.make().menus(
    m.group("business", "Business", icon="square-3-stack-3d", sequence=50).children([
        m.group("business.directory", "Directory", sequence=10).children([
            m.item("business.partners", "Partners")
            .view("partner.list")
            .sequence(10),
        ]),
        m.item("business.tags", "Tags")
        .parent(("admin", "settings.reference"))
        .view("tag.list")
        .sequence(20),
    ]),
)
```

| What you write | What gets stored |
|----------------|------------------|
| `m.group("business", …)` | Menu `name` = `business` in module `partners` |
| `m.group("…", parent="business")` | Nested group under `partners.business` |
| `parent="business.directory"` | `parent` = `partners.business.directory` |
| `parent=("admin", "settings.reference")` | `parent` = `admin.settings.reference` |
| `view="partner.list"` | `href` = `/web/views/partners/partner.list` |
| `href="/web/apps"` | Use for non-view routes (Dashboard, Apps) |
| `icon="home"` | [Heroicons](https://heroicons.com) name (outline by default) |

**Menu icons** use the [`heroicons`](https://pypi.org/project/heroicons/) package.
Pass a kebab-case name on groups and root-level items, e.g. `icon="chart-bar"`.
Variants: `icon="solid:shield-check"`, `icon="mini:bell"`, `icon="micro:bell"`.
Legacy inline SVG strings still work if they start with `<svg`.

Nested groups can use `m.group(...).children([...])` so `parent=` is set
automatically, or pass `parent=` explicitly on each entry. Menu names may
contain dots — use a short `parent="settings.organization"`, not a
hand-written `admin.*` string; see
[Navigation → Parent references](navigation.md#parent-references).

Low-level `menu_item` still works with full `href` and tuple parents if
you prefer raw dicts.

The framework upserts these into the `ir.ui.menu` table on every
install pass (parents before children), so re-declaring an entry
overwrites the previous one. After changing menus in a running app, use
**Apps → Sync** on that module.

## Custom HTTP routes

Declarative **views and menus** cover list/form/kanban pages under
`/web/views/…`. For bespoke pages (public forms, webhooks, custom dashboards),
declare **`WEB_ROUTES`** in the manifest:

```python
WEB_ROUTES: str = "mymodule.web:register_routes"
```

```python
# mymodule/web.py
def register_routes(app) -> None:
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    registry = app.state.registry
    pool = app.state.pool

    @app.get("/web/mymodule/hello", response_class=HTMLResponse)
    def hello():
        return "<p>Hello</p>"
```

`create_app()` discovers modules from **`module_roots`**, walks them in
`DEPENDS` order, and calls each registrar after core routes are mounted.
You do **not** wire module routes manually in `serve.py`.

**Reads as:** same discovery roots as install — if the module is on disk
under your roots and declares `WEB_ROUTES`, its URLs are live on boot and
after **Apps → Install** (no server restart required).

### Request scope and CSRF

Routes that use the ORM should build an `Environment` per request and call
**`pyvelm.request_env.apply_request_scope`** so session uid, company
cookie, and record rules match the admin UI. Full example:
`examples/modules/feedback_signals/web.py`.

Browser POST/PUT/DELETE must satisfy the same CSRF rules as core routes
(`pyvelm_csrf` cookie + `X-CSRF-Token` or `_csrf` form field).

## Loading a module

The loader is the entry point your app uses to bring modules online:

```python
from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

reg = Registry()
env = Environment(conn, registry=reg)
loader.load_and_install(
    BUILTIN_MODULE_ROOTS + ["/path/to/my/addons"],
    env,
)
```

`load_and_install(roots, env)` discovers every module under *roots* but
**only installs a subset** by default:

| Database state | Modules installed on boot |
|----------------|---------------------------|
| Fresh (empty `ir_module`) | Every module under **`pyvelm/modules/`** (e.g. `base`, `admin`, `reports`, …) |
| Already has installed rows | Only modules already in `ir_module` (sync/upgrade) |

Other discovered addons (outside the bundled tree) appear in **Apps** for
manual install. To install those too (demo scripts, CI), pass
``install_all=True`` to ``load_and_install`` or run ``pyvelm migrate --all``.

Steps:

1. **Discover** every directory containing a `__pyvelm__.py` under
   the given roots.
2. **Resolve order** by topologically sorting on `DEPENDS`. Cycles
   and missing deps raise.
3. **Load + install/sync** the subset from the table above (schema,
   hooks, views, menus).

Each step is callable on its own (`loader.discover`,
`loader.resolve_order`, `loader.install`) for finer control.

### `BUILTIN_MODULE_ROOTS`

The pyvelm wheel ships built-in modules under `pyvelm/modules/` —
`base` (framework primitives), `admin` (management UI), `reports`
(report builder), `document_layout` (company PDF layouts + print routes),
`file_manager` (attachment library), `console` (generators), and others.
They are exposed as
`pyvelm.BUILTIN_MODULE_ROOTS` — a single-entry list you prepend to
your own discovery roots. Apps that boot the framework should
always include it. `pyvelm-cron` prepends it automatically.

## Bumping versions and writing migrations

End-to-end workflow (diff → autogen → migrate → deploy): **[Migrations](migrations.md)**.

When you change a model's fields (or want to seed new data), bump
`VERSION` in the manifest:

```python
VERSION: tuple[int, ...] = (0, 2, 0)
```

Add a Python file under `migrations/` named after the transition:

```
partners/migrations/0_1_to_0_2.py
```

**The filename is load-bearing.** It must match
`<from>_to_<to>.py` with `_`-separated version parts. The loader
parses it and only runs scripts whose target version is greater
than the recorded version and less than or equal to the manifest
version — **not** on Apps **Sync** when versions already match.

For **idempotent backfills** (NULL rows before `SET NOT NULL`, orphan
column cleanup), use **`SYNC_HOOK`** instead. It runs before schema
apply on every upgrade, Sync, and `db migrate`. Migration scripts are
for version-gapped, one-time work (`ALTER TYPE … USING`, renames).

```python
# partners/hooks.py — runs on every Sync / migrate
def sync(env):
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"
```

### Seeders (Laravel-style)

Register seeders under ``<module>/seeders/`` — the loader reads
``seeders/__init__.py`` automatically (no manifest entry required):

```python
# myapp/seeders/database.py
from pyvelm.seeding import Seeder

class DatabaseSeeder(Seeder):
    def run_instance(self, env, **context):
        self.call(env, CountrySeeder)

# myapp/seeders/__init__.py
from .database import DatabaseSeeder

SEEDERS = [DatabaseSeeder]
```

Runs on **install**, **upgrade**, and **Sync** (after hooks and schema
apply). Write seeders to be **idempotent** — match existing rows on natural
keys and only insert or patch what is missing.

Override discovery with an explicit ``SEEDERS`` list in ``__pyvelm__.py``
when needed. Re-run manually with ``pyvelm db seed`` or ``pyvelm db seed myapp``.
Override ``should_run`` / ``enabled`` on the seeder class to skip optional work.
Heavy reference data (e.g. **geo_data**) uses batched inserts — see
[Geo data](geo-data.md).

Optional migration file for the same version bump (runs once on upgrade):

```python
from pyvelm.migrations import Blueprint, Schema, Table

def upgrade(env):
    schema = Schema(env)

    def _alter(t: Table) -> None:
        t.string("code", nullable=True)

    schema.table("res_partner", _alter)
    # Laravel-style FK: t.foreign("currency_id").constrained("res_currency")
    # Shorthand: t.foreign_id("currency_id", "res_currency", ondelete="SET NULL")
    # Column builders: Blueprint.supported_columns()
    # Backfill is in SYNC_HOOK — see partners/hooks.py
```

### Idempotency is your responsibility

The loader's safety net is version-based: once `ir_module` records
the new version, the migration won't re-run. Inside the migration:

- Use `ADD COLUMN IF NOT EXISTS` so an accidental replay survives.
- Filter the backfill (`("code", "=", None)`) so it only touches
  rows that still need it.
- For changes that aren't naturally idempotent (renames, type
  changes), the version filter is the safety net.

### Raw SQL and the cache

A bulk `UPDATE` that bypasses the ORM is fine for performance, but
the cache won't know about the change. Call
`env.cache.invalidate(model_name=…, fields=[…])` afterward if any
subsequent code in the migration reads the affected fields.

??? note "Why hand-written migrations"
    Auto-generated diffs are nice but committing to a diff engine
    pressures the project toward SQLAlchemy Core or an
    Alembic-equivalent — both heavier than pyvelm's current shape.
    The intent of a hand-written migration is more useful than the
    average generated one. When the migration count grows large
    enough that it hurts, auto-diff goes on the table.

## The Apps catalog

`/web/apps` is the visual addon-management page. It walks the
configured module roots on every load (so newly-dropped manifests
appear without restarting the server) and joins what it finds with
the `ir_module` table. Each module renders as a card with:

- Name, summary, author, optional icon.
- State badge — **Installed** / **Upgrade** / **Sync** / **Not installed**.
- Version line (or `installed → available` when an upgrade is
  pending).
- Dependency list. Names go red when a declared dep isn't
  installed yet; the install button stays disabled.

The toolbar above the cards lets you search by name/summary, filter
by state, and group by category.

### Install / upgrade / uninstall

Three buttons sit on every card; the framework gates all three
behind **uid=1 (superuser)** because they execute install hooks
and run DDL.

| Action | What happens |
|---|---|
| **Install** | Topologically installs the target and any uninstalled prerequisites. Models are imported into the live registry; the standard install pass runs (schema, hook, view/menu sync). Primary button on the card. |
| **Upgrade** | Shown only when the manifest version is ahead of the recorded `ir_module` version. Runs version-gap migration scripts and bumps the installed version. |
| **Sync** | Always available on installed modules. Re-applies schema diff and reloads views/menus from disk — highlighted when model/schema changes are pending without a version bump. |
| **Uninstall** | Drops tables owned by the module, deletes its `ir.ui.view` and `ir.ui.menu` rows, removes the `ir_module` entry. All inside one transaction. |

POST endpoints respond with `HX-Redirect: /web/apps` so the catalog
refreshes in place (with a `pv_flash` summary when applicable).
Installed modules that cannot be uninstalled show a disabled
**Protected** button with the blocker reason in its tooltip.

### Uninstall safety

Uninstall is the one with sharp edges. Before removing anything,
the framework runs `uninstall_preview` and returns a list of
**blockers** if it spots a problem:

- **`base` is the system module** — always blocked.
- **Bundled bootstrap modules** — every module under ``pyvelm/modules/``
  (``BOOTSTRAP_MODULES``) is protected the same way as ``base``.
- **Reverse dependencies** — any installed module whose manifest
  still lists this one in `DEPENDS` blocks the uninstall. Remove
  the dependent first.
- **`_inherit` base owners** — uninstalling a module that *owns*
  models is blocked while other **installed** modules still extend
  those models via `_inherit`. Uninstall the extensions first.
  Pure extension modules (they only `_inherit` someone else's
  model) remain uninstallable.

The UI disables the uninstall button when blockers exist (tooltip shows
why). The confirm dialog still re-checks blockers before any destructive
action runs.

`ir.model.access` and `ir.rule` entries seeded by install hooks
aren't tagged with the owning module, so they linger after
uninstall. Clean them up manually if you care.

## Transactions

`env.transaction()` is the explicit unit-of-work boundary. The
outer call opens a real transaction; nested calls become savepoints
so partial work can roll back.

```python
with env.transaction():
    alice.write({"name": "Alicia"})
    with env.transaction():
        carol.unlink()
        raise RuntimeError("boom")     # rolls back only the savepoint
    # alice's rename is still pending here
```

Outside any transaction, the connection runs in autocommit mode —
each ORM statement persists immediately. The transaction context
flips the connection out of autocommit for its duration.

??? warning "The cache doesn't roll back"
    `env.cache` does not undo writes on rollback. If a transaction
    fails after you read or wrote field values, the cache holds
    optimistic values that no longer match SQL. Drop the relevant
    entries with `env.cache.invalidate(model_name=…, fields=[…])`
    after a rollback if subsequent code in the same env cares about
    absolute truth. A proper savepoint-aware cache is on the list.
