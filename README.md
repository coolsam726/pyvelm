# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **Stage 4 Slice B.4 complete.** Views are records, declared
in module data files; a FastAPI app exposes both a JSON API
(`/api/views/...`, `/api/records` with full CRUD) and a bundled
HTMX + Tailwind UI with two view types (`list` and `form`),
inline edit / save / cancel / delete / new on lists, and
full single-record form pages. View inheritance is dict-merge with
Odoo XPath-position parity, addressing into list `fields` *and*
form `sections[*].fields`. A two-mode widget registry dispatches
rendering by `(field_type, hint, mode)`. Built on Stage 3 (module
loader, transactional install/upgrade, hand-written migrations) and
Stage 2 (ORM with all four relational field types, computed fields,
dotted-path traversal in both `@depends` and domains) — all on
PostgreSQL via psycopg 3.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env       # then edit PYVELM_DSN
.venv/bin/python examples/basic.py
```

The example exercises every feature: CRUD, recordset semantics, all four
relational field types, M2o traversal, computed fields, dependency-graph
invalidation, and the singleton guard.

## Documentation

- [Architecture overview](docs/architecture.md) — the big picture: why
  recordsets, what `env.cache` is for, how the dependency graph works, the
  multi-pass init sequence.
- [Module loading & migrations](docs/module-loading.md) — manifest format,
  loader lifecycle, the active-registry contextvar, writing migrations.
- [Web layer & views as data](docs/web-layer.md) — `ir.ui.view`, the
  `VIEWS` manifest key, the FastAPI app factory, JSON serialization
  shape.
- [Module reference](docs/modules.md) — what lives in each module, the
  public surface, and the invariants worth knowing.
- [Extending fields](docs/extending-fields.md) — implementing a custom field
  type without breaking the cache contract.
- [CONTEXT.md](CONTEXT.md) — current stage state, deferred items, and the
  next concrete task.

## What's deliberately not here yet

Things deferred with eyes open, not by accident: LRU/eviction on `env.cache`,
auto-generated schema diffs (migrations are hand-written),
Odoo-style M2M command tuples, transaction boundaries beyond psycopg
autocommit, schema migrations, module loading. See
[CONTEXT.md](CONTEXT.md) for the rationale.
