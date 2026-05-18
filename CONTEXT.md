# Project context

Building an Odoo-style ERP framework in Python. **Stage 2 is complete**:
declarative models, recordsets, full relational vocabulary (Many2one,
One2many, Many2many), and computed fields with a working `@depends`
dependency graph — all on PostgreSQL via psycopg 3.

For the design rationale and the deferred-items rationale, see
[docs/architecture.md](docs/architecture.md).

## Architectural decisions still in force

- Recordset-is-the-model: `BaseModel` instances represent 0/1/many records.
  Singleton access uses `ensure_one()`; the descriptor protocol routes
  field reads through `env.cache`.
- Field values live in `env.cache` keyed by `(model, id, field)`, NOT on
  instances. This is what makes computed-field invalidation tractable —
  and Stage 2 cashes that check.
- Environment is first-class and threads through every recordset. ACL,
  multi-company, context all flow through it (Stage 5 wires the ACL part).
- Sync ORM. Async only at the FastAPI/HTTP boundary later.
- PostgreSQL from the start (psycopg 3, sync). Raw SQL by string concat
  for now; SQLAlchemy Core (not ORM) is on the table for Stage 3.

## Roadmap

1. ✅ Declarative model layer + recordsets + CRUD/search.
2. ✅ Relational fields (Many2one, One2many, Many2many) + computed fields
     with `@depends` + dependency graph.
3. ⏭ Module loading + schema migrations + registry lifecycle. Also a
     natural home for: domain traversal (`country_id.code`) + multi-hop
     `@depends` since both need a shared dotted-path parser. Consider
     migrating raw SQL to SQLAlchemy Core here.
4. Views (form/list/kanban) as data + generic UI endpoints.
5. ACL: groups, model permissions, record rules (domain-based row security).
6. Workflows: server actions, automated actions, scheduled jobs, mail threads.
7. Module inheritance: `_inherit` for models, XPath-style view patches.

## Deliberately deferred (will bite us, fix when they do)

- `env.cache` has no LRU or eviction. Fine until working sets get large.
- Domain language is AND-only, no relational traversal, no polish notation.
- Multi-hop `@depends` (e.g. `country_id.region_id.name`); only single-hop
  through Many2one is supported. Traversal through One2many/Many2many is
  not supported (needs the same dotted-path parser as domain traversal).
- No caching for One2many/Many2many reads — re-queried each access.
- Stale FK cache on comodel unlink: `ON DELETE SET NULL` updates the DB,
  but the cache still holds the old int. Needs a reverse-FK index.
- M2M command tuples (`[(0,_,vals)]`, `[(4,id)]`) — current write is
  replace-only.
- Stored compute backfill on schema add (real migrations are Stage 3).
- No transaction boundaries beyond psycopg autocommit.
- SQL by string concat (works because inputs are controlled at every call
  site; domain values flow through parameterized binds).
- `registry` is a module global (fine until Stage 3 module loading needs
  per-module slices).

## Next concrete task

Stage 3, with one architectural pivot up front: build the **dotted-path
parser** that unlocks both domain traversal and multi-hop `@depends`. That
parser is the prerequisite for:

- `Partner.search([("country_id.code", "=", "FR")])`
- `@depends('country_id.region_id.name')`
- O2m/M2m caching (uses the same reverse-walk machinery)

Then the proper Stage 3 work — module loading, migrations, registry
lifecycle. Possibly migrate raw SQL to SQLAlchemy Core in the same pass to
get a real migration tool for free.
