# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **Stage 3 Slice A complete.** On top of the Stage 2 ORM
(declarative models, recordsets, all four relational field types,
computed fields with dotted-path `@depends`), modules are now discovered
on disk via `__pyvelm__.py` manifests, installed in dependency order,
and upgraded via hand-written migrations — all transactional, all on
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
