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

Stage 2.5 is now complete: the dotted-path parser feeds both the
`@depends` dependency graph and the domain compiler. M2o-only paths emit
shared `LEFT JOIN` chains; any path containing an O2m/M2m hop emits a
per-leaf `EXISTS` subquery (`Partner.search([("tag_ids.name", "=",
"VIP")])` works).

Stage 3 next: module loading + migrations + registry lifecycle. Possibly
migrate raw SQL to SQLAlchemy Core in the same pass to get a real
migration tool for free. One smaller follow-up that can slot in before
Stage 3 if it hurts first:

- **O2m/M2m caching + old-value snapshotting** — closes the remaining
  invalidation gaps (stale FK cache on comodel unlink; lost-parent
  invalidation when a child re-parents). Worth doing together since both
  touch the same `model.write` read-before-write hook.
