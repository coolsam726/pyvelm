# Project context

Building an Odoo-style ERP framework in Python. **Stage 4 first slice
is complete**: views are data (`ir.ui.view` records, upserted from
module manifests' `VIEWS` key), and a FastAPI app exposes generic
read-only endpoints over them with JSON serialization of recordsets.
Built on top of Stage 3 (module loader, transactional install/upgrade,
hand-written migrations) and Stage 2 (ORM with all four field types,
dotted-path `@depends`, M2o LEFT-JOIN + O2m/M2m EXISTS domain
traversal) — all on PostgreSQL via psycopg 3.

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
     ⏭ Slice B (deferred): module data (seed records beyond views),
        auto-diff schema migrations (SQLAlchemy Core?), down-migrations
        or formal rollback story.
4. ⏭ Views (form/list/kanban) as data + generic UI endpoints.
     ✅ Slice A: `ir.ui.view` records, `VIEWS` manifest key with
        upsert-by-(module, name), FastAPI app factory with
        `/api/views/{module}/{name}` + `/api/records`, JSON serializer
        (Many2one → `[id, display]`, collections → id lists),
        connection-pool-backed Environment-per-request.
     ✅ Slice B.1: view inheritance via typed dict-merge ops
        (`set`/`replace`/`remove`/`before`/`after`), arch
        normalization, `VIEW_INHERITS` manifest key, `priority`-driven
        chain resolution, `/api/views` returns resolved arch.
     ⏭ Slice B.2: HTMX + Jinja renderer that walks the resolved arch.
        Form / kanban view types and their normalizers come with it.
     ⏭ Slice B.3: mutation endpoints (POST/PATCH/DELETE) shared by
        JSON API + HTMX form submits.
     ⏭ Slice B.4: `pyvelm.types` TypedDicts for IDE assistance on
        manifest authoring (Manifest, View, Operation).
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

Stage 4 Slice B.1 landed: view inheritance via typed dict-merge
operations, with a third example module (`partners_pro`) patching
`partner.list` end-to-end. Resolution walks the chain in priority
order, normalization at install lets authoring stay terse, the
`/api/views` endpoint always returns the resolved arch. `Field.default`
finally applies at `create()` time — was on the deferred list, fixed
in passing since `priority = Integer(default=16)` needed it.

Next: **Slice B.2 — the HTMX + Jinja renderer.** The renderer is the
visible payoff: a default list-view UI ships in the framework, fed
from the resolved arch, with HTMX wiring up pagination and edit
interactivity. Form view type comes along with it (the arch normalizer
gains a `form` entry, the view declarations support sections/groups,
the Jinja template renders the dispatched widgets).

After B.2: B.3 (mutation endpoints), B.4 (TypedDicts for IDE
assistance). Stage 5 (ACL / record rules) is the natural pairing with
mutations — public write endpoints without row-level security would be
malpractice.

Still deferred: cache snapshot on transaction rollback,
O2m/M2m caching + old-value snapshotting, auto-diff schema migrations.
None pressing.
