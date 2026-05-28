# Migrations workflow

pyvelm uses **versioned, hand-written migrations** per module, plus **additive
schema sync** on every install/upgrade. This page is the recommended workflow for
a greenfield app and for production deploys.

## Two layers (Odoo-style)

| Layer | When it runs | What it does |
|-------|----------------|---------------|
| **Model-driven diff** | `pyvelm db diff` anytime | Compares every stored field to Postgres: new columns, nullability, **type** mismatches, orphan columns |
| **Schema apply** | Every install/upgrade/`db migrate` | `_setup_table` + `apply_schema_diff` — new tables/columns, `SET NOT NULL` when no NULL rows, `DROP NOT NULL` when relaxing |
| **`SYNC_HOOK`** | Before schema apply on every upgrade/**Sync**/migrate | Idempotent backfills, orphan-column cleanup, and other fixups so `SET NOT NULL` can run in the same pass |
| **Migration scripts** | Only when `ir_module.version` **&lt; manifest `VERSION`** | `migrations/<from>_to_<to>.py` — one-time, version-gapped transforms: `ALTER TYPE … USING`, renames, DDL autogen cannot emit |

### What `pyvelm db migrate` actually runs

For an **already-installed** module, `db migrate` (and **Apps → Upgrade / Sync**) always:

1. Reload models and `DATA` from disk
2. Run **`SYNC_HOOK`** (if declared)
3. Apply **additive schema diff** (`_setup_table` + `apply_schema_diff`)
4. Re-sync views and menus

It does **not** re-execute migration `.py` bodies when the manifest version already
matches `ir_module` (the common **Sync** path). Those scripts run **once per version
gap** — strictly between the recorded version and the bumped manifest — inside
`loader.install()` before the sync hook.

**Rule of thumb:** put idempotent **data backfills** (NULL → value before `SET NOT NULL`)
and **orphan column drops** (columns removed from the model but still in Postgres) in
**`SYNC_HOOK`**. Keep migration files for irreversible or version-gapped work that
should not run on every Sync (type casts with `USING`, renames, one-off transforms).
Autogen may still write a migration stub when you bump `VERSION`; treat the hook as
the place that makes `db migrate` / Sync succeed on databases that already had rows.

Like Odoo **Upgrade**: changing a model and migrating applies new columns and tightens
NOT NULL when the data is already clean. **Diff** still reports type changes and
`SET NOT NULL` while NULL rows exist.

### What `pyvelm db diff` detects

| Change | Reported as | Auto on Upgrade/Sync? |
|--------|-------------|------------------------|
| New table / column | `+ table` / `+ column` | Yes |
| `required=True`, DB nullable, no NULL rows | `~ … set_not_null` | Yes (`SET NOT NULL`) |
| `required=True`, DB nullable, NULL rows exist | `~ … set_not_null` | No — backfill in **`SYNC_HOOK`** first |
| `required=False`, DB NOT NULL | `~ … drop_not_null` | Yes (`DROP NOT NULL`) |
| Field type ≠ column type | `~ … type mismatch` | No — needs `USING` |
| Column removed from model | `- orphan` | No |

## Day-to-day developer loop

1. **Edit models** in `app/modules/<name>/models/`.
2. **Check the delta:**
   ```bash
   pyvelm db diff <module>
   ```
3. **Generate a migration** (bumps `VERSION` in `__pyvelm__.py`):
   ```bash
   pyvelm db autogen <module>
   # optional: scaffold list+form views for new models
   pyvelm db autogen <module> --with-views
   ```
4. **Review** `migrations/*_to_*.py` and **`SYNC_HOOK`** — autogen strips
   `NOT NULL` on `ADD COLUMN` when the table may already have rows. Put
   idempotent backfills and orphan cleanup in the sync hook (see partners
   `hooks.py`); keep the migration file for version-gapped DDL (`USING`, renames).
5. **Apply locally:**
   ```bash
   pyvelm db migrate
   ```
   Or open **Apps → Upgrade** on the module (same install pass).
6. **Commit** the migration file and the bumped `VERSION`.

Filename convention: `0_1_to_0_2.py` matches `VERSION` tuple `(0, 2, 0)` after
the bump. See [Modules → Bumping versions](modules.md#bumping-versions-and-writing-migrations).

## Deploy / CI (before app workers)

Run migrations **once** per deploy, then start gunicorn:

```bash
export PYVELM_DSN=postgresql://...
export PYVELM_MODULE_ROOTS=/app/app/modules   # if needed
pyvelm db migrate
gunicorn -c gunicorn_conf.py app.serve:app
```

For **manual production** deploys, prefer `migrate-fresh` so you see the module
plan and must confirm before anything runs:

```bash
export PYVELM_ENV=production
pyvelm db migrate-fresh              # prompts: type migrate-fresh
pyvelm db migrate-fresh --dry-run    # plan only
pyvelm db migrate-fresh --module base
```

CI pipelines can use `pyvelm db migrate` or `pyvelm db migrate-fresh --yes`.

Docker Compose (scaffolded projects) includes a one-shot `migrate` service that
runs before `app` — see `docker-compose.yml`.

`app/serve.py` still calls `load_and_install` on boot (idempotent). With
`pyvelm db migrate` in your deploy pipeline, workers only repeat work if someone
skips the migrate step.

## Inspect versions

```bash
pyvelm db status
```

Lists each discovered module, the on-disk manifest version, and whether
`ir_module` is missing, in sync, or needs upgrade.

## Commands reference

| Command | Purpose |
|---------|---------|
| `pyvelm db diff <module>` | Print schema delta (no writes) |
| `pyvelm db autogen <module>` | Write migration file + bump `VERSION` |
| `pyvelm db migrate` | Install/upgrade all modules |
| `pyvelm db migrate-fresh` | Same as migrate, with plan + production confirmation |
| `pyvelm db status` | Installed vs manifest versions |

All require `PYVELM_DSN`. Module roots: `pyvelm.toml` + `PYVELM_MODULE_ROOTS` (same
as `app/serve.py`). Separate paths with **commas or colons**:

```bash
PYVELM_MODULE_ROOTS=./examples/modules,./examples/modules_demo
# or
PYVELM_MODULE_ROOTS=./examples/modules:./examples/modules_demo
```

Run CLI commands from the project directory (or any parent with a `.env`), so
`load_dotenv` picks up your file.

## Existing columns (required / type)

If you change `required` on a column that **already exists**, `diff` reports `~` lines.
**Migrate / Upgrade / Sync** applies `SET NOT NULL` when every row has a value;
otherwise backfill in **`SYNC_HOOK`**, then run `pyvelm db migrate` (or Sync) again.
**Type changes** are never auto-applied. **Orphan columns** (`- orphan` in diff) are
never auto-dropped — remove them in **`SYNC_HOOK`** when you are ready.

Example:

```text
~ res_partner.code: model required=True, DB allows NULL — backfill NULLs, then SET NOT NULL
      → db migrate will NOT apply SET NOT NULL yet: 3 row(s) have NULL in res_partner.code
```

That is **not** a missing migration file — `db migrate` already ran. It **refused** `SET NOT NULL`
because Postgres rejects it while NULLs exist. Backfill, then `pyvelm db migrate` again.

Partners example — backfill lives in **`SYNC_HOOK`** (`partners/hooks.py`), not only
in `migrations/0_1_to_0_2.py`, so **Sync** (same version) and every `db migrate` pass
can fill NULLs before `SET NOT NULL`:

```python
def sync(env):
    Partner = env["res.partner"]
    for partner in Partner.search([("code", "=", None)]):
        prefix = (partner.name or "?")[:3].upper()
        partner.code = f"{prefix}-{partner.id}"
```

Then `pyvelm db migrate` and `pyvelm db diff partners` should be clean for that line.

## What autogen will not do

- Column **renames** (would drop + add — hand-write `ALTER … RENAME`)
- **Type changes** (need `USING` clauses)
- **M2M junction tables** (ORM creates them at install)
- **Down migrations** (one-way only)

## Still manual

- Idempotent **data backfill** and **orphan column drops** in **`SYNC_HOOK`**
- Version-gapped **`migrate(env)`** for `USING` casts, renames, and other one-off DDL
- `env.cache.invalidate(...)` after raw SQL that bypasses the ORM
- Stored-compute **recompute** when adding a new stored computed field

See [Architecture → Deliberately deferred](architecture.md#deliberately-deferred)
for transaction/cache limits.
