# Project context

Building an Odoo-style ERP framework in Python. **Stage 3 first slice
is complete**: module loader (`__pyvelm__.py` manifests, dep
resolution, per-module install), `ir_module` version tracking,
hand-written migrations, transactional install/upgrade. Built on top of
the Stage 2 ORM (recordsets, four relational field types, computed
fields with dotted-path `@depends`, M2o LEFT-JOIN and O2m/M2m EXISTS
domain traversal) — all on PostgreSQL via psycopg 3.

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
  for now; SQLAlchemy Core (not ORM) still on the table when migration
  auto-diff becomes interesting.
- **No module-global registry.** `Registry` is a first-class object;
  models register into whichever registry is active (a contextvar). The
  loader sets it around each module's models import. Defining a model
  with no active registry raises — silent fallbacks make multi-registry
  bugs hard to find.
- **Migrations are hand-written, one-way, per-module.** Auto-diff is
  deferred; SemVer comparison is element-wise on a version tuple. The
  installer is atomic per module (one transaction each).

## Roadmap

1. ✅ Declarative model layer + recordsets + CRUD/search.
2. ✅ Relational fields + computed fields with `@depends`.
     ✅ Stage 2.5: dotted-path parser, M2o LEFT JOIN, O2m/M2m EXISTS.
3. ⏭ Module loading + migrations + registry lifecycle.
     ✅ Slice A: manifests, dep resolution, per-module install,
        `ir_module` tracking, hand-written migrations, transactions.
     ⏭ Slice B (deferred): module data (seed records, view definitions),
        auto-diff schema migrations (SQLAlchemy Core?), down-migrations
        or formal rollback story.
4. Views (form/list/kanban) as data + generic UI endpoints.
5. ACL: groups, model permissions, record rules (domain-based row security).
6. Workflows: server actions, automated actions, scheduled jobs, mail threads.
7. Module inheritance: `_inherit` for models, XPath-style view patches.

## Deliberately deferred (will bite us, fix when they do)

- `env.cache` has no LRU or eviction. Fine until working sets get large.
- Domain language is AND-only, no relational traversal, no polish notation.
- Universal-quantifier domains on collections: `("tag_ids.name", "!=",
  "VIP")` reads "has at least one non-VIP tag," not "every tag is
  non-VIP." The latter needs `NOT EXISTS` semantics or an explicit `all`
  operator.
- Old-value invalidation on O2m/M2m: when a child moves from parent A to
  parent B, only B's dependent computes get invalidated; A's stay stale
  until the next read. Needs read-before-write in `model.write`.
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

Stage 3 Slice A landed and is now exercised by a real migration:
`partners` is at `(0, 2, 0)` with a `code` field on Partner and a
`0_1_to_0_2.py` migration that ALTERs the table and backfills via the
ORM. Verdict: the design holds up but has a known tax — the new field
lives in both the model class (for fresh installs) and the migration
DDL (for upgrades). Tolerable at one-field scale.

Things that could go next, roughly by "what'll hurt first":

1. **Cache snapshot on `env.transaction()`** — the cache currently
   holds optimistic values that survive a rollback. We document the
   workaround (`env.cache.invalidate(...)` after rollback); ideally the
   transaction context handles it.
2. **O2m/M2m caching + old-value snapshotting on M2o writes** — closes
   the remaining invalidation gaps from Stage 2. Independent of Stage
   3 plumbing.
3. **Stage 4: views as data + generic UI endpoints** — the architectural
   next thing. Builds directly on what we have.

Auto-diff schema migrations get more interesting once the migration
count grows. One field isn't enough signal yet; revisit when it
becomes annoying.
