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
4. ✅ Views (list/form/kanban) as data + generic UI endpoints. See
     CONTEXT history for the Slice A..B.6 sub-stages.
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
     ✅ Slice B.3: mutation endpoints (POST/PATCH/DELETE on
        /api/records) + HTMX inline edit. Per-field edit-mode widgets,
        `parse_form_vals` for type coercion, row-level edit/save/
        cancel/delete/new/create endpoints. Boolean hidden+checkbox
        pair handles unchecked-as-false correctly.
     ✅ Slice B.4: form view type. Normalizer entry for
        `sections[*].fields`; render at `/web/views/.../record/{id}`
        (display / edit) and `/new` (create); HX-Request header
        switches between full-page and body-fragment responses for
        the same handler. Section-level inheritance verified in the
        example (partners_pro renames a section title and patches
        field attrs across the section path).
     ✅ Slice B.5: kanban view type. Cards grouped into columns by a
        configurable field (Many2one or scalar); each card carries
        title/subtitle/fields/badges and optionally links to a form
        view. Reuses display-mode widget registry; no edit mode in
        kanban (click → form view for editing).
     ✅ Slice B.6: `pyvelm.types` TypedDicts for IDE assistance.
        Manifest, View, ViewInherit, Operation, and per-view-type
        arch shapes exported from `pyvelm.types`. Examples annotated
        (`VIEWS: list[View]`, `VIEW_INHERITS: list[ViewInherit]`,
        manifest globals with explicit types) so Pyright/Pylance
        catch typos at edit time.
5. ⏭ ACL: groups, model permissions, record rules (domain-based row security).
     ✅ Slice A: res.groups, res.users (bcrypt), ir.model.access,
        ir.rule. HTTP Basic auth in `pyvelm.web`. Superuser bypass at
        uid=1. Demo seeds Admin + Partner Manager + record rule.
     ✅ Slice B: session cookies + form login. `res.users.session_token`
        (Char, nullable) added with migration 0_3_to_0_4. `/login` GET
        renders Tailwind login form; POST validates credentials, writes
        a `secrets.token_hex(32)` token, and sets an HttpOnly/SameSite=Lax
        `pyvelm_session` cookie then 303-redirects. `/logout` POST clears
        the token in DB and deletes the cookie. `get_env` checks the
        session cookie first; HTTP Basic auth is the secondary fallback
        (machine clients still work unchanged).  Base module bumped to
        (0, 4, 0).
     ✅ Slice C: admin module. New `examples/modules/admin` depends on
        `base`; ships list+form views for all four ACL models
        (res.groups, res.users, ir.model.access, ir.rule) via a `DATA`
        file. Install hook grants Admin full CRUD on those models.
        `/web/admin` dashboard (Tailwind card grid) links to all 8
        views; unauthenticated hits redirect to `/login?next=/web/admin`.
        All views reuse the existing form/list renderers — no new Python
        models needed.
6. ✅ Workflows: server actions, automated actions, scheduled jobs, mail threads.
     ✅ Slice A: `ir.actions.server` model (`pyvelm/actions.py`).
        `action_type` ∈ {write, create, unlink, code}. `run(records)`
        dispatches accordingly; `code` actions use `exec()` with an env
        containing `env`, `records`, and `action`. Granted to Admin via
        base hooks; migration in 0_4_to_0_5.
     ✅ Slice B: `base.automation` model (`pyvelm/automation.py`).
        Triggers: on_create / on_write / on_unlink. `AutomationEngine.fire()`
        searches active rules per (model, trigger) and runs the linked
        `ir.actions.server`. Wired into `BaseModel.create`, `.write`,
        `.unlink` via lazy import. Errors are logged to stderr, non-fatal.
        Skips during `_acl_bypass` (system bootstrap) to avoid recursion.
     ✅ Slice C: `ir.cron` model (`pyvelm/cron.py`). Fields: name,
        action_id, interval_number, interval_type, nextcall, active.
        `_DatetimeField` accepts `datetime` objects or ISO strings.
        `CronJob.run_due(env)` queries active jobs with `nextcall ≤ now`,
        runs each linked action, advances `nextcall` by the configured
        interval (minutes/hours/days/weeks), returns set of run job names.
     ✅ Slice D: `mail.message` model + `MailThread` mixin
        (`pyvelm/mail.py`). Message fields: model, res_id, author_id,
        body, message_type, subtype, date. `MailThread.message_post()`
        creates a `mail.message` keyed to the current record.
        `message_ids` property queries all messages for the record.
        Model added to base module and granted to Admin.
     Base module bumped to 0.5.0; migration 0_4_to_0_5 creates four
     tables: ir_actions_server, base_automation, ir_cron, mail_message.
7. ✅ Module inheritance: `_inherit` for models.
     ✅ Slice A+B: `_inherit` in `MetaModel.__new__`. When a class sets
        `_inherit = "some.model"` without a new `_name`, the metaclass
        looks up the existing class, creates a proper Python subclass of
        it (so `super()` chains via MRO), merges in new fields, binds
        compute methods, and replaces the registry entry. The original
        model's methods/fields are accessible through normal MRO.
     ✅ `_setup_table` made idempotent: Phase 1 is the existing
        `CREATE TABLE IF NOT EXISTS (all cols)`, Phase 2 issues
        `ALTER TABLE ADD COLUMN IF NOT EXISTS` for each stored field so
        extending modules can add columns to already-installed tables.
     ✅ `Registry._model_extensions` tracks which models each module
        extended via `_inherit`. `_load_models` detects class replacements
        and records them. `_setup_module_schema` includes extended models
        so new columns are added during the extending module's install.
     ✅ `partners_pro` upgraded from view-only to full model extension:
        `PartnerPro(_inherit="res.partner")` adds `vip_note Char` and
        overrides `_compute_display_name` to prefix VIP partners with ★.
        `super()` correctly chains to the base `Partner` implementation.
     ✅ 5 smoke tests verifying: field presence, write/read of new field,
        overridden compute, super() chain, non-VIP baseline.
     ⏭ Slice C (deferred): XPath-style view arch patches (structural
        view patches beyond the existing dict-op VIEW_INHERITS mechanism).

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

Stage 8 (multi-company) landed in 0.6.0 but had three UX/design bugs
that made the demo silently lie:
  1. `BaseModel.search` skipped the company filter for superuser, so
     the company switcher did nothing when demoing as admin.
  2. Login didn't pre-set the `pyvelm_company` cookie from
     `user.company_id`, so a freshly-logged-in user saw a "scope
     inactive" view until they manually clicked the switcher.
  3. The install hook seeded a global `ir.rule` doing the same job
     as `BaseModel.search`'s `_company_scoped` filter, with
     contradictory semantics (the rule allowed NULL company_id;
     the model filter excluded it). `_rule_needs_company_skip`
     existed only to silence the rule when no scope was active.

**0.7.0 standardizes:** the model-level filter is the single source
of truth for company scope. It applies to everyone (superuser included)
whenever `env.company_id` is set on a `_company_scoped` model. Login
pre-sets `pyvelm_company` from `user.company_id`. The buggy global
rule is gone (migration `0_6_to_0_7.py` prunes it from older installs).
`_company_scoped` was also dropped from `res.users` — users carry a
`company_id` but stay cross-company-visible so the admin UI can
manage them all.

UI polish landed: pyvelm now ships an Odoo-Enterprise-style shell
(persistent sidebar with multi-level menu, sticky topbar, theme
toggle, company switcher, user menu) backed by a local
Tailwind v4 + Flowbite build pipeline:

- `package.json` + `npm install` pulls Tailwind 4.1 and Flowbite 3.1.
- `npm run build` compiles `pyvelm/static/tailwind.css` → minified
  `pyvelm/static/dist/pyvelm.css`, then copies `flowbite.min.js` next
  to it. `npm run dev` watches.
- The dist directory is checked in so the Python smoke test still
  runs out of the box; `node_modules/` is gitignored.
- Master template `pyvelm/templates/layouts/main.html` provides the
  shell. Every page renderer (list, form, kanban, admin) now passes
  `layout_context(env, current_path)` so the shell knows the active
  user, company, menu state, and current path.
- Theme toggle and sidebar-collapse persist via `localStorage`. The
  layout also ships a small Alpine-driven dialog component
  (`pvConfirm` / `pvAlert`) for future replacement of `hx-confirm`
  browser prompts.
- Login page stays standalone (no shell) and uses the same compiled
  stylesheet for consistency.

UI polish wave (post-0.7.0):

  - **Layout system** — proper page heading region (h2 + subtitle +
    breadcrumb), unified across list/form/kanban/admin via
    `render.layout_context()`. `build_breadcrumbs(menu, current_path,
    leaf_label)` derives crumbs from the menu tree.
  - **DataTable** (`templates/list.html` + `list_table.html`) — Alpine
    `pvList` component adds per-column filters, drag-and-drop column
    reorder with `localStorage` persistence, and search/sort on top of
    the existing HTMX pagination. No external table lib.
  - **Many2one combobox** — Odoo-style searchable relation widget at
    `widgets/m2o_input.html` + `pvM2o` Alpine component. Endpoints
    `GET /api/m2o/search` and `POST /api/m2o/quick-create` drive
    debounced search, keyboard nav, "Create '<query>'" inline, and
    "Create and edit…" navigation. Display mode wraps the label in a
    hover-revealing "open record" link via `_form_view_for_model`.
  - **`ir.ui.menu`** (0.8.0) — sidebar is now data-driven. Each module
    contributes entries via a `MENUS` list in a data file; the loader's
    `_sync_menus` upserts them with `(module, name)` identity (mirrors
    `ir.ui.view`). Parents reference `<module>.<name>`; sequence orders
    siblings. `render._menu(env, current_path)` walks the table at
    render time and emits the two-level tree. Migration `0_7_to_0_8`
    creates the table for upgraded installs.
  - **Auth hardening** — every `/web/*` mutation route (row + form
    save/edit/delete/create) now checks `env.uid` up front and returns
    `HX-Redirect` for HTMX callers, 302 for direct navigation, 401 for
    JSON. Logout adds `Clear-Site-Data: "cache", "cookies"` so the
    browser bfcache can't replay an authenticated page after Back.
  - **Autosave on navigation** — edit/new forms render with
    `data-pv-autosave="<save-url>"` on `<form>`; a layout-level script
    snapshots `FormData` at mount and after every `htmx:afterSwap`,
    marks the form dirty on input, and intercepts internal `a[href]`
    clicks to POST first and navigate on success. `beforeunload` falls
    back to the native prompt because async work can't complete on
    hard navigations.

Next focus options:
  - **Adopt the `pvConfirm` dialog** — replace remaining `hx-confirm`
    browser prompts in `list_row.html` / `form_body.html` with the
    styled dialog component (`data-pv-confirm` triggers).
  - **Flowbite form-control polish** — improve edit-mode widget styling
    using Flowbite form-control patterns (labels, helper text, error
    states).
  - **Stage 7 Slice C**: XPath/structural view arch patches.
  - **Stage 6 hardening**: Cron as a real background task, SMTP mail
    dispatch, message subtypes, followers/subscriptions.
  - **Stage 5 hardening**: CSRF tokens, rate limit /login, password-
    change UI.

Still deferred: cache snapshot on transaction rollback, O2m/M2m
caching + old-value snapshotting, auto-diff schema migrations,
field-level validation feedback in the inline-edit form, multi-
select widget for O2m/M2m editing, row-level reorder via a `sequence`
field (Odoo "handle" widget), "Create and edit…" modal (combobox
currently navigates to /new), m2o result caching beyond in-flight
requests. None pressing.
