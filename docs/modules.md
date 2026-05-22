# Modules

A pyvelm **module** is a Python package on disk that ships some
combination of models, views, and seed data. Modules are the unit of
install, upgrade, and uninstall — they're how you ship your code as
a self-contained piece other apps can depend on or extend.

## Shape on disk

```
mymodule/
├── __init__.py          # can be empty
├── __pyvelm__.py        # manifest (NAME, VERSION, DEPENDS, DATA, …)
├── models/
│   ├── __init__.py      # imports every model file
│   └── partner.py
├── views/
│   ├── __init__.py
│   └── partner.py       # exports VIEWS = [...] / VIEW_INHERITS = [...]
└── migrations/          # optional
    ├── __init__.py
    └── 0_1_to_0_2.py
```

## The manifest

`__pyvelm__.py` is plain Python — module-level constants the loader
reads. The minimum is two keys:

```python
NAME: str = "partners"
VERSION: tuple[int, ...] = (0, 1, 0)
```

Most modules also declare:

```python
DEPENDS: list[str] = ["base"]
DATA: list[str] = ["views/partner.py", "views/tag.py"]
INSTALL_HOOK: str = "partners.hooks:install"
```

Everything else is optional. `DEPENDS` is what the loader uses to
topologically order installs; `DATA` lists Python files whose
module-level `VIEWS`, `VIEW_INHERITS`, and `MENUS` lists feed the
declarative-data sync; `INSTALL_HOOK` is a `pkg.mod:fn` reference
to a function called once on first install (it gets the
`Environment`).

`pyvelm.types.Manifest` is a TypedDict that documents every
recognised key. Annotating each global with its declared type lets
your IDE catch typos like `DEPNEDS` at edit time. The loader
ignores the annotations.

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
from pyvelm import BaseModel, Char, Integer, Many2one


class Partner(BaseModel):
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
DATA = ["views/partner.py", "views/menu.py"]
```

The loader executes each file and harvests the module-level lists:

- `VIEWS` — base view declarations.
- `VIEW_INHERITS` — patches against other modules' views.
- `MENUS` — sidebar entries.

```python
# partners/views/partner.py
from pyvelm.builders import list_view, form_view, section

VIEWS = [
    list_view("partner.list", "res.partner",
              fields=["name", "code", "country_id"]),
    form_view("partner.form", "res.partner",
              sections=[
                  section("identity", "Identity", ["name", "code"]),
                  section("location", "Location", ["country_id"]),
              ]),
]
```

Files that don't define any of those lists are still imported — use
this for side-effects like registering custom widgets via
`@pyvelm.render.widget`.

## Sidebar menus

A `MENUS` list contributes entries to the left-hand sidebar.
Top-level **groups** have an optional `icon` and no `href`; **leaf items**
link to a view (or other URL) and sit under a **parent** group.

Use the **`Menus`** builder so you only pass names you already know from
`VIEWS` and `menu_group` — not hand-built `/web/views/...` paths or
`"<module>.<group>"` strings:

```python
# partners/views/menu.py  —  NAME in __pyvelm__.py is "partners"
from pyvelm.builders import Menus

m = Menus("partners")

MENUS = [
    m.group("business", "Business", icon=_ICON_GRID, sequence=50),
    # parent="business"  →  partners.business
    # view="partner.list"  →  /web/views/partners/partner.list
    m.item("business.partners", "Partners",
           parent="business", view="partner.list", sequence=10),

    # Cross-module parent: admin owns the Settings group
    m.item("business.tags", "Tags",
           parent=("admin", "settings"), view="tag.list", sequence=40),
]
```

| What you write | What gets stored |
|----------------|------------------|
| `m.group("business", …)` | Menu `name` = `business` in module `partners` |
| `parent="business"` | `parent` = `partners.business` |
| `parent=("admin", "settings")` | `parent` = `admin.settings` |
| `view="partner.list"` | `href` = `/web/views/partners/partner.list` |
| `href="/web/apps"` | Use for non-view routes (Dashboard, Apps) |

Low-level `menu_group` / `menu_item` still work with full `href` and
`parent="partners.business"` if you prefer raw dicts.

The framework upserts these into the `ir.ui.menu` table on every
install pass, so re-declaring an entry overwrites the previous one.

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

`load_and_install(roots, env)` runs three steps end to end:

1. **Discover** every directory containing a `__pyvelm__.py` under
   the given roots.
2. **Resolve order** by topologically sorting on `DEPENDS`. Cycles
   and missing deps raise.
3. **Install** each module in dependency order: schema setup for
   new modules, migrations for upgrades, and the data-file sync
   pass either way.

Each step is callable on its own (`loader.discover`,
`loader.resolve_order`, `loader.install`) for finer control.

### `BUILTIN_MODULE_ROOTS`

The pyvelm wheel ships two modules — `base` (framework primitives)
and `admin` (the UI for them). They live at
`pyvelm/modules/<name>/` inside the package and are exposed as
`pyvelm.BUILTIN_MODULE_ROOTS` — a single-entry list you prepend to
your own discovery roots. Apps that boot the framework should
always include it. `pyvelm-cron` prepends it automatically.

## Bumping versions and writing migrations

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
version.

```python
def migrate(env):
    # 1. Schema change.
    env.conn.execute(
        'ALTER TABLE "res_partner" '
        'ADD COLUMN IF NOT EXISTS "code" text'
    )
    # 2. Backfill via the ORM. partner.code = … goes through the
    #    descriptor and updates env.cache, so subsequent reads
    #    see the new value without manual invalidation.
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"
```

The function receives a live `Environment`. Use the ORM or drop to
raw SQL via `env.conn.execute(...)` — your choice. The migration
runs inside the installer's per-module transaction.

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
- State badge — **Installed** / **Upgrade →** / **Not installed**.
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
| **Install** | Topologically installs the target and any uninstalled prerequisites. Models are imported into the live registry; the standard install pass runs (schema, hook, view/menu sync). |
| **Upgrade** | Re-runs the install pass so version-gap migrations execute and data files re-sync. Note: new field declarations only take effect after a process restart — the DB schema is migrated but the in-memory model class isn't reloaded. The confirm prompt calls this out. |
| **Uninstall** | Drops tables owned by the module, deletes its `ir.ui.view` and `ir.ui.menu` rows, removes the `ir_module` entry. All inside one transaction. |

POST endpoints respond with `HX-Redirect: /web/apps` so the sidebar
re-renders (newly-installed modules may have added menu entries).

### Uninstall safety

Uninstall is the one with sharp edges. Before removing anything,
the framework runs `uninstall_preview` and returns a list of
**blockers** if it spots a problem:

- **`base` is the system module** — always blocked.
- **Reverse dependencies** — any installed module whose manifest
  still lists this one in `DEPENDS` blocks the uninstall. Remove
  the dependent first.
- **`_inherit` extensions** — modules that extend models owned by
  another module can't be uninstalled cleanly. Their added columns
  sit on someone else's table and the framework doesn't track
  per-module column ownership.

The UI surfaces these via the styled alert dialog instead of
routing into the confirm flow — there's no destructive path to
confirm.

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
