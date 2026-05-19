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
- **UI stack: Tailwind CSS (Play CDN) + HTMX.** Major deviation from
  Odoo's Bootstrap. Templates emit utility classes directly; the
  framework ships no component-class CSS. JSON arch is the contract
  for both the bundled HTMX renderer and any SPA built against the
  JSON API.
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
        (`set`/`replace`/`update`/`remove`/`before`/`after`), arch
        normalization, `VIEW_INHERITS` in manifest data files,
        `priority`-driven chain resolution, granular attribute ops
        (Odoo `position="attributes"` parity), `/api/views` returns
        resolved arch.
     ✅ Slice B.2: HTMX + Jinja list renderer with widget registry
        (Char/Integer/Float/Boolean[+toggle]/Many2one/collections),
        `/web/views/{m}/{n}` full pages, `/web/records/{m}/{n}`
        fragment endpoint with OOB load-more swap. UI stack uses
        Tailwind CSS via Play CDN (major deviation from Odoo's
        Bootstrap); widgets emit utility classes directly.
     ⏭ Slice B.3: mutation endpoints (POST/PATCH/DELETE) shared by
        JSON API + HTMX form submits; click-to-edit in list view.
     ⏭ Slice B.4: form + kanban view types (normalizer + template +
        widget conventions per type).
     ⏭ Slice B.5: `pyvelm.types` TypedDicts for IDE assistance on
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

Stage 4 Slice B.2 landed: the framework now ships a default UI. List
views render to HTML via a Jinja template that dispatches each field
through a widget registry; HTMX handles pagination via OOB swaps; a
minimal CSS skin makes the demo look acceptable. No developer-written
templates — the arch + widget hints drive everything.

Next: **Slice B.3 — mutation endpoints + click-to-edit.** POST/PATCH/
DELETE on `/api/records`; HTMX-driven inline edit in the list view
that reuses the same handlers under the hood. This is the largest
single slice left in Stage 4 because it touches request-body
validation, write paths, error mapping, and cache-rollback semantics
that we've been documenting around.

After B.3: B.4 (form + kanban view types), B.5 (TypedDicts for IDE
assistance). Stage 5 (ACL / record rules) is the natural pairing with
mutations — public write endpoints without row-level security would be
malpractice.

Still deferred: cache snapshot on transaction rollback,
O2m/M2m caching + old-value snapshotting, auto-diff schema migrations.
None pressing.
