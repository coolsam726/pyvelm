# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **Stage 5 Slice A complete.** Access control + HTTP Basic
auth land on top of Stage 4's full UI: `res.groups`, `res.users`
(bcrypt), `ir.model.access`, `ir.rule` enforce per-model CRUD perms
and AND-inject row-level filters into every search. Anonymous reads
are denied unless a `group_id=None` grant exists; HTTP Basic against
`res.users.login` populates `env.uid`; superuser at uid=1 bypasses.
On top of Stage 4 (three view types, mutations, inheritance,
TypedDicts), Stage 3 (module loader, migrations), and Stage 2 (ORM
with all four relational field types, computed fields, dotted-path
traversal) — all on PostgreSQL via psycopg 3. View inheritance is dict-merge with
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
  shape, three view types, mutations, inline edit.
- [Access control](docs/acl.md) — the four ACL models, HTTP Basic
  authentication, superuser bypass, record rules, anonymous access
  conventions.
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
