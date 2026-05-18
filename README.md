# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **Stage 2 complete.** Declarative models, recordsets, full relational
vocabulary (Many2one, One2many, Many2many), computed fields with a working
`@depends` dependency graph, all on PostgreSQL via psycopg 3.

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
- [Module reference](docs/modules.md) — what lives in each module, the
  public surface, and the invariants worth knowing.
- [Extending fields](docs/extending-fields.md) — implementing a custom field
  type without breaking the cache contract.
- [CONTEXT.md](CONTEXT.md) — current stage state, deferred items, and the
  next concrete task.

## What's deliberately not here yet

Things deferred with eyes open, not by accident: LRU/eviction on `env.cache`,
domain traversal (`partner.search([('country_id.code', '=', 'FR')])`),
multi-hop `@depends` (`@depends('country_id.region_id.name')`),
Odoo-style M2M command tuples, transaction boundaries beyond psycopg
autocommit, schema migrations, module loading. See
[CONTEXT.md](CONTEXT.md) for the rationale.
