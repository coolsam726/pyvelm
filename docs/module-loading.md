# Module loading & migrations

This guide covers the Stage 3 lifecycle: defining a pyvelm module on
disk, getting it discovered, installed into a database, and upgraded
between versions. For the rationale behind the design choices, see
[architecture.md](architecture.md#stage-3-module-lifecycle).

## The shape of a module

A pyvelm module is a Python package containing a `__pyvelm__.py`
manifest:

```
mymodule/
├── __init__.py          # can be empty
├── __pyvelm__.py        # manifest (NAME, VERSION, DEPENDS, ...)
├── models/
│   ├── __init__.py      # imports every model file
│   ├── partner.py
│   └── tag.py
└── migrations/          # optional
    ├── __init__.py
    └── 0_1_to_0_2.py
```

The manifest is plain Python. Minimum:

```python
NAME = "partners"
VERSION = (0, 1, 0)
DEPENDS = ["base"]
```

Optional manifest keys:

- `MODELS_PACKAGE` — dotted import path for the models package
  (default: `<package>.models`).
- `MIGRATIONS_PACKAGE` — dotted import path for the migrations package
  (default: `<package>.migrations`).
- `INSTALL_HOOK` — dotted reference (`pkg.mod:fn`) called once when the
  module is installed for the first time. Receives the `Environment`.

The package must be importable. The loader adds each scan root to
`sys.path` so siblings under that root are top-level imports.

## Loading

```python
from pyvelm import Environment, Registry, loader

reg = Registry()
env = Environment(conn, registry=reg)
specs = loader.load_and_install(["/path/to/modules"], env)
```

`load_and_install` is the convenience wrapper. It runs three steps:

1. **`discover(roots)`** — walk each root, find directories containing
   `__pyvelm__.py`, parse manifests into `ModuleSpec` objects.
2. **`resolve_order(specs)`** — topo-sort by `DEPENDS`; raise on cycles
   or missing deps.
3. **`install(specs, env)`** — per module, in order, run the appropriate
   schema setup / migration / hook inside a transaction.

Each piece is callable on its own if you need finer control (e.g.
discover from multiple roots, filter before installing).

## The active-registry contextvar

There is no module-global registry. Models register into whichever
registry is "active" at class-creation time. The loader sets the
active registry around each module's models import:

```python
with registry.activate():
    importlib.import_module(spec.models_package)
```

If you define models outside the loader (tests, scripts), bracket the
class definitions yourself:

```python
reg = Registry()
with reg.activate():
    class Partner(BaseModel):
        _name = "res.partner"
        ...
```

Defining a model with no active registry raises `RuntimeError` — there
is no silent fallback. This is deliberate: with multiple registries in
play, a "default" silently steals registrations and creates bugs that
are hard to find.

## Schema lifecycle

`install(specs, env)` walks specs in topo order. For each module:

- **First time seen** (no row in `ir_module`):
  - `CREATE TABLE` for that module's stored models.
  - `ALTER TABLE ADD CONSTRAINT` for FK columns whose targets exist
    (intra-module + dependencies that were installed earlier in this
    same call).
  - `CREATE TABLE` for Many2many junctions owned by these models.
  - Run `INSTALL_HOOK(env)` if declared.
  - `INSERT` into `ir_module` with the manifest version.

- **Already installed, older version**:
  - Import every `*.py` file under `MIGRATIONS_PACKAGE` (sorted by
    filename) and call its `migrate(env)`.
  - `UPDATE ir_module` to the new version.

- **Already installed, same version**: no-op.

Every per-module step runs inside its own `env.transaction()`. A
failure mid-install rolls back just that module's changes; previously
installed modules stay installed. This is intentional: the alternative
(one big transaction across all modules) makes "module B failed to
install" mean "we don't know what state any module is in," which is
hostile to debugging.

After all per-module work succeeds, the loader does two whole-registry
passes once:

1. `_build_compute_graph()` — `@depends` paths can cross module
   boundaries (e.g. `partners.Partner.display_name` depending on
   `base.Region.name`), so the graph is rebuilt from the union of all
   loaded models.
2. `_validate_relations(self)` — One2many inverses and Many2many
   comodels are checked now that everything is in scope.

These can't run earlier because the cross-module references aren't
resolvable until both sides are loaded.

## Writing a migration

A migration is a Python file under `<module>/migrations/` exporting a
`migrate(env)` function. **The filename is load-bearing**: it must
match `<from>_to_<to>.py` where each version part is `_`-separated
(e.g. `0_1_to_0_2.py`). The loader parses this and only runs scripts
whose target version `>` the recorded version and `<=` the manifest
version. Files that don't match the convention raise; throwaway docs
or helpers should live somewhere outside this directory.

```python
# partners/migrations/0_1_to_0_2.py
def migrate(env):
    # 1. Schema change: add the new column.
    env.conn.execute(
        'ALTER TABLE "res_partner" ADD COLUMN IF NOT EXISTS "code" text'
    )
    # 2. Backfill via the ORM. partner.code = ... goes through the
    # descriptor and updates env.cache, so subsequent reads see the
    # new value without manual invalidation.
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"
```

The function receives a live `Environment`. You can use the ORM
(`env["res.partner"].search(...)`) or drop to raw SQL via
`env.conn.execute(...)`. The whole migration runs inside the
installer's per-module transaction.

**Idempotency is your responsibility.** Defensive patterns to know:

- `ADD COLUMN IF NOT EXISTS` — survives an accidental replay.
- Filter the backfill (`("code", "=", None)`) so it only touches rows
  that still need it.
- For schema changes that aren't naturally idempotent (renames, type
  changes), the version filter is your safety net — the loader won't
  call your script again once `ir_module` records the new version.

**The "same column in two places" trade-off.** A fresh install creates
the new column from the model class declaration; an upgrade creates it
in the migration. The column lives in two places because there's no
auto-diff. For a single field this is mild; for a wave of schema
changes it gets verbose. If you feel it consistently, that's the
signal to design auto-diff (see CONTEXT.md).

**Raw SQL that bypasses the ORM** (e.g. a bulk `UPDATE` that doesn't
go through `partner.write(...)`) is fine for performance, but the
cache won't know about the change. Call
`env.cache.invalidate(model_name=..., fields=[...])` afterward if any
subsequent code in the migration reads the affected fields.

## Transactions

`env.transaction()` is the explicit unit-of-work boundary. Outer call
opens a real transaction; nested calls become savepoints so partial
work can roll back.

```python
with env.transaction():
    alice.write({"name": "Alicia"})
    with env.transaction():
        carol.unlink()
        raise RuntimeError("boom")   # rolls back only the savepoint
    # alice's rename is still pending here
```

Outside any transaction, the connection runs in autocommit mode — each
ORM statement persists immediately. This matches how the examples have
worked since Stage 1. The transaction context flips the connection out
of autocommit for its duration.

**Cache and rollback.** The cache does *not* roll back automatically.
If a transaction fails after you read or wrote field values, the cache
holds optimistic values that no longer match SQL. The right pattern
for now is to drop the relevant cache entries (`env.cache.invalidate(...)`)
after a rollback if subsequent reads care about absolute truth. A
proper savepoint-aware cache is a deferred item.

## Migration design choices

- **No auto-diff yet.** Migrations are hand-written. Auto-generated
  diffs are nice but committing to a diff engine pressures the project
  toward SQLAlchemy Core (or an Alembic-equivalent), and the readable
  intent of a hand-written migration is more useful than the average
  generated one. When the migration count grows large, revisit.
- **No down-migrations.** Pyvelm migrations are one-way. The migration
  filename names the *transition* (`0_1_to_0_2.py`), not the target
  version. Rollback strategy in production is restore-from-backup
  plus re-install at the older version.
- **Module versions are tuples.** `(0, 1, 0)` compares element-wise; no
  pre-release suffixes, no SemVer parser. Add when needed.
