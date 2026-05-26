# Project context — pyvelm v0.11.0

Building an Odoo-style ERP framework in Python.

**v0.11.0 (released 2026-05-26)** — **Email templates** (`mail.template`),
**Html** field sanitizer, TipTap v3 + CodeMirror editor, live Jinja preview,
form **cols** / **colspan** grid. Base **0.26.0**. See
[CHANGELOG.md](CHANGELOG.md) and [docs/releases/v0.11.0.md](docs/releases/v0.11.0.md).
**v0.10.0 (released 2026-05-26)** — **Policies** on ACL, **UI action/menu gating**,
**access denied** page, **landing** + `PYVELM_HOME_URL`, **sudo**, **public
attachments**, **User** group no longer re-added on sync. See
[CHANGELOG.md](CHANGELOG.md) and [docs/releases/v0.10.0.md](docs/releases/v0.10.0.md).
**v0.9.0 (released 2026-05-25)** — **Kanban** (grid, filters, drag-drop), **schema
diff/migrate**, **dialog** O2M/M2M widgets, **breadcrumb history** (`ref`/`bc`),
framework **timestamps**, `make:view` from model. See
[docs/releases/v0.9.0.md](docs/releases/v0.9.0.md).
**v0.8.0 (released 2026-05-25)** — **White-label branding** per company (`res.company`
+ `PYVELM_*`), login/profile chrome, date/datetime picker fixes (no double calendar;
floating popups in inline O2M tables). Base module **0.21.0**. See
[CHANGELOG.md](CHANGELOG.md) and [docs/releases/v0.8.0.md](docs/releases/v0.8.0.md).
**v0.7.0 (released 2026-05-23)** — Form **chatter** (Activity panel), **`tracking=True`**
field changes, workflow **history** timeline, form activity layout. See
[docs/releases/v0.7.0.md](docs/releases/v0.7.0.md).
**v0.6.0 (released 2026-05-23)** — Visual **Workflows**: designer, runtime bar,
approvals inbox, stage forms, auto-start, escalation cron. See
[docs/releases/v0.6.0.md](docs/releases/v0.6.0.md) and [docs/workflow.md](docs/workflow.md).
**v0.5.0 (released 2026-05-23)** — Per-company theme, declarative dashboards,
date/datetime/time pickers, list column picker, account profile, Feedback Signals
example. See [CHANGELOG.md](CHANGELOG.md) and [docs/releases/v0.5.0.md](docs/releases/v0.5.0.md).
**v0.4.0 (released 2026-05-22)** — Visual **Report Builder**: drill-down field
picker, column formatting, order by, Excel/CSV/PDF export, daily cron.
See [CHANGELOG.md](CHANGELOG.md), [docs/releases/v0.4.0.md](docs/releases/v0.4.0.md),
and [docs/report-builder.md](docs/report-builder.md).
**v0.3.0 (released 2026-05-22)** — Apps Sync, Vellum timestamps/`_guarded`,
`display_name`, console UX polish. See [CHANGELOG.md](CHANGELOG.md) and
[docs/releases/v0.3.0.md](docs/releases/v0.3.0.md).
**v0.2.9 (released 2026-05-23)** — Domain `{"all": True}`; GitHub releases from
CHANGELOG. See [v0.2.9 release summary](#v029-release-summary).
**v0.2.8 (released 2026-05-23)** — Symmetric M2M cache; docs home refresh.
See [v0.2.8 release summary](#v028-release-summary).
**v0.2.7 (released 2026-05-23)** — Domain `__or__` + collection paths; comodel
unlink M2O cache invalidation. See [v0.2.7 release summary](#v027-release-summary).
**v0.2.6 (released 2026-05-22)** — Vellum ORM veneer (slices A–D), O2M/M2M
request cache, docs + smoke example. See [v0.2.6 release summary](#v026-release-summary).
**v0.2.5 (released 2026-05-22)** — Artisan console, generators, dev/prod
runtime, reload registry fix. See [v0.2.5 release summary](#v025-release-summary).
**v0.2.4 (released 2026-05-22)** — Menus builder, CLI module discovery,
sidebar icon fix. See [v0.2.4 release summary](#v024-release-summary).
**v0.2.3 (released 2026-05-22)** — related fields + model-level readonly.
See [v0.2.3 release summary](#v023-release-summary).
**v0.2.2** — Docker scaffold bind-mount for `app/modules`
([summary](#v022-release-summary)).
**v0.2.1** — inline O2m, M2m polish, field labels
([summary](#v021-release-summary)).
**v0.2.0** — graph/pivot, attachments, security
([summary](#v020-release-summary)).

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
- **UI stack: Tailwind v4 + Flowbite (local build) + HTMX + Alpine.js.**
  Major deviation from Odoo's Bootstrap. `npm run build` compiles
  `pyvelm/static/dist/pyvelm.css` (checked in for clone-and-run). Templates
  emit utility classes directly. JSON arch is the contract for both the
  bundled HTMX renderer and any SPA built against the JSON API.
- **No module-global registry.** `Registry` is a first-class object;
  models register into whichever registry is active (a contextvar). The
  loader sets it around each module's models import. Defining a model
  with no active registry raises — silent fallbacks make multi-registry
  bugs hard to find.
- **Migrations are hand-written, one-way, per-module.** SemVer comparison is
  element-wise on a version tuple. Install/upgrade also runs additive
  `db_autogen.apply_schema_diff` and `pyvelm db autogen` can draft migration
  files — not a full Alembic/down-migration story. The installer is atomic per
  module (`env.transaction()` per module in `loader.install`).

## Roadmap

1. ✅ Declarative model layer + recordsets + CRUD/search.
2. ✅ Relational fields + computed fields with `@depends`.
     ✅ Stage 2.5: dotted-path parser, M2o LEFT JOIN, O2m/M2m EXISTS.
3. ✅ Module loading + migrations + registry lifecycle.
     ✅ Slice A: manifests, dep resolution, per-module install,
        `ir_module` tracking, hand-written migrations, `env.transaction()`.
     ✅ Slice B (partial): `DATA` manifest loads `.py` data files
        (VIEWS, VIEW_INHERITS, MENUS); `INSTALL_HOOK` / `SYNC_HOOK` for
        seed logic; Apps **Install / Upgrade / Sync / Uninstall**;
        additive schema via `_setup_table` + `db_autogen` on install/sync;
        `pyvelm db diff` / `pyvelm db autogen` CLI.
     ⏭ Still out of scope: `.json`/`.yaml` data files, down-migrations,
        full SQLAlchemy-Core auto-diff engine, cache restore on rollback.
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
        fragment endpoint with OOB load-more swap.
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
     ✅ Slice B.7: `pyvelm.builders` factory helpers. Named
        constructor functions replace raw dicts in data files:
        `list_view`, `form_view`, `kanban_view` (with `section`,
        `field`, `card` sub-helpers), `inherit_view` + six `op_*`
        helpers (`op_remove`, `op_set`, `op_update` with **kwargs,
        `op_after`, `op_before`, `op_replace`), `Menus` (sidebar:
        short `parent` / `view` names), `menu_group` and `menu_item`,
        `Command` (Artisan-style CLI — `make:model` / `make:view` /
        `make:menu`; see `docs/console.md`).
        Every function returns the matching TypedDict
        so the loader needs no changes. `pyvelm.types` updated to
        discriminated union views (`ListView`/`FormView`/`KanbanView`
        with Literal `view_type` discriminants) so Pyright narrows
        `arch` to the correct shape; `ArchList`/`ArchForm` expanded
        with optional `title`/`form_view`/`sequence` keys. `Menu`
        TypedDict added. All example data files (partners, crm,
        admin, base) rewritten to use builders.
5. ✅ ACL: groups, model permissions, record rules (domain-based row security).
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
     ✅ Slice C: admin module (`pyvelm/modules/admin`) depends on
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
     ✅ Slice C: structural view arch patches. Target segments now
        accept dict-shaped **predicates** (match list entries by any
        attribute, equivalent to Odoo's `xpath="//tag[@a='x']"`) and
        a leading `"**"` **wildcard** that anchors the lookup at any
        descendant where the next segment would succeed. Demoed via
        `partner.form.pro.xpath` — predicate sets readonly on every
        toggle-widget field; `**` labels `tag_ids` without hard-coding
        its section path.
8. ✅ Report Builder: secure declarative reports + visual builder UI.
     ✅ `reports` module (`ir.report`, `ir.report.run`, module version
        `0.2.0`): definition schema v1, SQL compiler (M2o joins,
        O2m/M2m correlated subqueries), ACL + record rules + company
        scope, preview/execute/export.
     ✅ Visual builder at `/web/reports/build`: 4-step wizard, Odoo-style
        field drill-down (`GET /api/reports/field-level`), per-column
        format/align/currency, multi-field order by (including fields not
        in columns), filters + runtime parameters, list + summary modes.
     ✅ Export: Excel/CSV/PDF; daily cron scheduling with attachment
        output and run audit log (`ir.report.run`).
     ✅ `pvCombo` searchable combobox; list `record_href` / `create_href`
        for custom open/create URLs.
     Docs: [docs/report-builder.md](docs/report-builder.md).
9. ✅ Greenfield projects — `pyvelm init` (Docker + `app/serve.py` +
     `pyvelm.toml`), `pyvelm new` / `make:module`, bundled scaffolds.
     [docs/getting-started.md](docs/getting-started.md) walks a new app
     from install to first custom module.
10. ✅ Graph & pivot views — ApexCharts graph; cross-tab pivot;
     `/api/graph/data`, `/api/pivot/data`.
11. ✅ Multi-company — `env.company_id`, company switcher, model-level
     `_company_scoped` filter (applies to superuser when scope is set);
     login pre-sets `pyvelm_company` cookie (0.7.0 cleanup).
12. ✅ Visual workflow module (0.6.0) — designer, runtime bar, approvals
     inbox, stage forms, auto-start, escalation cron. Optional `workflow`
     module; see [docs/workflow.md](docs/workflow.md).
13. ✅ Form chatter + tracking (0.7.0) — Activity panel, `tracking=True`,
     workflow history timeline. `pyvelm/mail_chatter.py`, `mail_tracking.py`.
14. ✅ Attachments, dashboards, mail outbox, Vellum ORM veneer — see
     CHANGELOG 0.2.0–0.5.0 and shipped-features log below.

## Greenfield readiness (v0.8.0)

The framework is ready for a **new project trial**: scaffold with
`pyvelm init`, add modules with `pyvelm new`, install from **Apps**, seed
ACL in `hooks.py`, hand-write migrations when the schema changes. The
`examples/` tree remains the reference implementation; it is not what
`init` ships (fresh installs start with `base` + `admin` only).

**Migrations:** use [docs/migrations.md](docs/migrations.md) — `pyvelm db diff` /
`autogen` / `migrate` / `status`; Docker scaffold runs `db migrate` before app.

Operational caveats for production pilots are listed under
[Still deferred](#still-deferred) — mostly multi-worker ergonomics and
API ergonomics, not missing core CRUD/UI/security.

## v0.11.0 — email templates (shipped)

See [docs/releases/v0.11.0.md](docs/releases/v0.11.0.md). Key paths:
`mail_template.py`, `mail_template_render.py`, `mail_template_fields.py`,
`html_sanitizer.py`, `static/src/mail_editor.js`, migration `0_25_to_0_26`.
**Editor:** `mail_editor.js` loads in `<head>` **before** Alpine (`defer`).
**Post-release polish ideas:** shallow variable API, subject-line insert UX,
example `send_mail` in a demo module.

## Deliberately deferred (will bite us, fix when they do)

| Gap | Status |
|-----|--------|
| `env.cache` LRU / eviction | Still open — one env per request, working set usually bounded. |
| Cache restore on `env.transaction()` rollback | Still open — DB rolls back; session cache is not snapshotted. |
| M2M command tuples `[(0,_,vals), (4,id), …]` | Still open — Many2many write is **replace-only** (`fields.py`). |
| Stored compute backfill on new stored fields | Still open — hand-written migration or manual recompute when needed. |
| Universal CRUD in one transaction | Partial — `env.transaction()` + savepoints used by `loader.install` and key `/web` mutations; ad-hoc ORM calls outside a transaction still autocommit per statement. |
| SQL string-built queries | By design — domain values use parameterized binds; table/column names from registry metadata. |
| i18n / translations | Still open — no gettext layer. |
| Down-migrations / formal rollback | Still open — one-way migrations only. |
| Shared login rate limit across gunicorn workers | Still open — per-worker window; proxy-side limiter recommended ([docs/deployment.md](docs/deployment.md)). |
| One-shot deploy migrate | **`pyvelm db migrate`** + optional Compose `migrate` service — see [docs/migrations.md](docs/migrations.md). Workers may still idempotently `load_and_install` on boot. |
| Nested / stacked `PvDialog` instances | Still open — single floating dialog. |

**Fixed since older CONTEXT drafts (no longer deferred):**

- **O2m inverse cache on reparent** — `write()` snapshots `before_m2o` and
  `_invalidate_relational_caches` clears the old parent's One2many tuple
  (`model.py`).
- **Module `DATA` files** — loader `_load_data_files` + sync on upgrade.
- **Additive schema on sync** — `db_autogen.apply_schema_diff` after migrations.
- **Session login + CSRF + rate limit** — shipped in auth hardening wave.
- **Double datepicker / clipped pickers in inline tables** — fixed in v0.8.0
  (`pvInitDatepickers`, floating datetime panel).

## Current release — v0.11.0

**Email templates**, **`Html`** sanitizer, TipTap v3 + CodeMirror editor, live
Jinja preview, form **cols** / **colspan**. **Upgrade:** `pip install -U pyvelm`,
`pyvelm db migrate` (base **0.26.0**), `npm run build:editor` if hacking UI,
hard-refresh browser.

Prior headline releases: **v0.10.0** policies/gating, **v0.9.0** kanban/autogen,
**v0.8.0** branding — see [CHANGELOG.md](CHANGELOG.md).

### Report builder — known limits (unchanged)

- Summary group-by drill-down: root-model fields only (no `partner_id.country_id` paths).
- Detail columns: stored fields only at validate time.
- No seeded sample report in `vellum_demo` yet.

## Shipped features log (pre-v0.3.0)

Chronological feature log kept for reference. Structured release summaries
for v0.3.0+ are in the sections below.

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
  layout also ships draggable confirm/alert prompts (`pvConfirm` /
  `pvAlert` via `PvDialog.confirm` / `.alert`) on the same chrome as
  inline form dialogs.
- Login page stays standalone (no shell) and uses the same compiled
  stylesheet for consistency.

UI polish wave (post-0.7.0):

  - **Layout system** — proper page heading region (h2 + subtitle +
    breadcrumb), unified across list/form/kanban/admin via
    `render.layout_context()`. `build_breadcrumbs` yields
    Home → list (linked on form pages) → record title; list pages
    show Home → view label only.
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
  - **pvConfirm interceptor** — one `htmx:confirm` listener routes
    every `hx-confirm` through the draggable `PvDialog` confirm mode.
    Templates unchanged.
  - **Flowbite form-control polish** — semantic-token inputs, Text
    fields render as `<textarea>`, required `*` indicator surfaces.
  - **Human-readable page headings** — `_view_title(view, arch)` reads
    `arch["title"]` then falls back to `_humanize_model(view.model)`.
  - **Per-view auto-rendered table heading** — `arch["title"]` plus
    `_humanize_model` fallback (e.g. `crm.lead` → `Leads`).
  - **Odoo-style list search** — single search bar with chip filters
    replacing the per-column filter row. Filter By + Group By dropdown
    auto-generates entries from `filter_kind` / `group_kind` per
    header. Group By renders the table as collapsible buckets.
  - **Apps catalog** — `/web/apps` lists every module the loader can
    find under `module_roots`, joining disk manifests with `ir_module`
    rows. Cards show state (Installed / To upgrade / Not installed),
    version, deps. Superuser-gated install / upgrade / uninstall
    endpoints; uninstall has a dry-run preview that blocks unsafe
    operations (system module, reverse-deps, `_inherit` extensions).
    Optional manifest fields (`SUMMARY`, `DESCRIPTION`, `CATEGORY`,
    `AUTHOR`, `ICON`) drive the card content.
  - **Demo seed module** — `examples/modules_demo/demo` lives in its
    own discovery root so `serve.py` boots into a populated app
    (~20 partners, 15 leads, tags, extra sales users, workflow
    examples, mail thread) while `basic.py` keeps its minimal
    Alice/Bob/Carol fixture. INSTALL_HOOK is idempotent — re-runs
    are safe; uninstall drops the row but leaves seeded content
    (the documented limitation).
  - **Apps catalog filter** — client-side search + state pills
    (All / Installed / Upgrade / Not installed) + category dropdown
    on `/web/apps`. Filtering composes with AND, runs entirely in
    Alpine (no server roundtrip), empty categories collapse their
    header.

Form-UX completeness wave (commits `1b9121d`, `d99bad4`, `558d3dd`):
  - **Inline validation errors.** `parse_form_vals` returns
    `(vals, errors)`; required-empty + type-coercion failures stamp
    per-field messages; save returns 422 + edit fragment with errors
    + submitted values resurrected so the user doesn't retype.
    ORM-level failures land in a top-level banner. `htmx:beforeSwap`
    listener opts 422 responses into the normal swap pipeline;
    inline-row routes emit `HX-Trigger: pv-validation-error` toast
    via `pvAlert`.
  - **Many2many chip editor** (`widgets/m2m_input.html` + `pvM2m`
    Alpine component). Selected records render as removable chips
    (one hidden input per id, plus an always-empty marker so the
    server tells "cleared" from "field not present"). Search input
    hits `/api/m2o/search`; results filter out already-selected ids.
    `parse_form_vals` M2m branch runs ahead of the `is_stored` gate.
  - **Drag-reorder via `sequence`.** A list view opts in via
    `arch["sequence"] = "<integer-field>"`. Renderer adds a handle
    column, forces sort, disables pagination. Native HTML5 drag
    handlers POST `{ids: […]}` to
    `/web/records/{module}/{name}/reorder`; server rewrites the
    field to `(position+1) × 10`. Wired up on `res.tag` —
    `partners` bumped to 0.3.0 with migration 0_2_to_0_3, admin
    module gains `tag.list` / `tag.form` views.

Auth & deployment hardening wave (commits `9520446`, `095c768`,
`a82791f`, `1a7985d`, `f5bd894`):
  - **CSRF tokens.** `CsrfMiddleware` mints `pyvelm_csrf` cookie
    (SameSite=Lax, not HttpOnly), validates via `X-CSRF-Token`
    header or `_csrf` form field on every unsafe method. Exemptions:
    Basic-auth requests (machine clients) and cookie-less calls.
    HTMX integration is automatic via `htmx:configRequest`; plain
    `<form method="post">` gets a hidden `_csrf` auto-injected by a
    DOMContentLoaded + `htmx:afterSwap` handler. Non-HTMX fetches
    (apps uninstall, row reorder, m2o quick-create, form autosave)
    call `window.pvCsrf()` to add the header explicitly.
  - **/login rate limit.** Per-IP in-memory sliding window, 5
    attempts per 5 min → 429 + `Retry-After`. Both successful and
    failed attempts count. Per-worker — multi-worker deployments
    multiply the cap by N, called out in deployment doc with the
    proxy-side limiter as the production answer.
  - **Self-service password change.** `/web/account/password` form
    (current / new / confirm). bcrypt verify + length + match +
    ≠current checks; new value written through the Password field
    which re-hashes on store. ACL-bypassed read so users without
    explicit res.users access still self-serve. New entry in the
    user-menu dropdown.
  - **Deployment.** Multi-stage `Dockerfile` (node build CSS →
    python runtime, non-root user), `gunicorn_conf.py` (UvicornWorker
    + env-driven knobs), `docker-compose.yml` with postgres-16
    sidecar + health check + named volume, `.dockerignore`, expanded
    `.env.example`. New deployment doc section walks the four
    scale-out gotchas (per-worker rate limit, X-Forwarded-For trust,
    pool sizing, where to put a CDN).

  ✅ **Nuru-style shell** (github.com/coolsam726/nuru) implemented:
  - **Sidebar**: flattened to flat nav with small uppercase
    section-label separators; no `<details>`/chevron. Active item
    retains soft primary-tint background + primary text.
  - **Topbar**: app name ("pyvelm") fixed on the left; page title
    stays in the page-heading region below. `{% block page_title %}`
    kept in a `sr-only` span so `self.page_title()` still works.
  - **Table**: leftmost checkbox column added (future bulk selection);
    `py-2.5` → `py-1.5` on thead/tbody for slimmer rows; drag-grab
    icon removed from column headers (drag handle kept on
    sequence-reorder rows only); Boolean display widget changed from
    checkmark/X to colored Yes/No badge pill
    (`bg-success-soft text-fg-success-strong` / `bg-neutral-tertiary
    text-body-subtle`). CSS rebuilt.
  Files touched: `layouts/main.html`, `list_table.html`,
  `list_row.html`, `list_row_edit.html`, `render.py`,
  `static/dist/pyvelm.css`.

  ✅ **Author-side IDE help** for view declarations:
  - **Builders** (`pyvelm.builders`): `field`, `section`, `card`,
    `list_view`, `form_view`, `kanban_view`, `inherit_view`,
    `op_set / op_replace / op_update / op_remove / op_after /
    op_before`, `Menus`, `menu_group`, `menu_item`. Each returns the matching
    TypedDict; storage shape unchanged.
  - **Discriminated `View` union**: `ListView` / `FormView` /
    `KanbanView` each lock `view_type` to a `Literal` and `arch` to
    the matching arch shape. Pyright narrows from the discriminant
    so typing `"view_type": "list"` instantly autocompletes `arch`
    against `ArchList`.
  - **`WidgetHint = Literal["toggle"]`** drives autocomplete on
    every field-spec; new hints land here as the registry grows.
  - **`TargetSegment` union** lifts the `"**"` wildcard into an
    explicit `Literal` so the segment list autocompletes the
    wildcard prefix.
  - **Required-key bases** on every authoring TypedDict (`View`,
    `ViewInherit`, `Operation`, `FieldRef`, `ArchList`, `ArchForm`,
    `ArchSection`, `Manifest`) — missing required keys now squiggle
    at edit time instead of failing at install.

  ✅ **Stage 6 hardening — cron runner + outgoing-mail dispatcher**:
  - `pyvelm.cli.cron_loop` + `pyvelm-cron` console_script tick
    `CronJob.run_due` at `PYVELM_CRON_INTERVAL` (default 60s).
    SIGTERM/SIGINT graceful drain. Dedicated `cron` service in
    docker-compose, pinned at replicas: 1 because run_due does plain
    SELECT-then-UPDATE (FOR UPDATE SKIP LOCKED is the future fix).
  - `mail.message` gains `recipient_email` / `subject` / `state`
    (outgoing/sent/failed) / `error`. `Message.dispatch_outgoing(env)`
    drains the queue via a pluggable backend (`PYVELM_MAIL_BACKEND` =
    `console` | `disabled` | `smtp` with PYVELM_SMTP_* knobs).
    `MailThread.notify()` is the queue-it-and-log sugar. base/hooks
    seeds the dispatcher cron + server action; 0_8_to_0_9 migration
    adds the columns + calls the same seed for upgraded installs.
    base bumped to 0.9.0.

  ✅ **Bundled modules**: `base`, `admin`, `reports`, `console`, `vellum`, and
  others ship inside the wheel at `pyvelm/modules/<name>/`.
  `pyvelm.BUILTIN_MODULE_ROOTS` is the single-entry list apps prepend to
  their discovery roots; the `pyvelm-cron` CLI prepends it automatically. A poison
  `pyvelm/modules/__init__.py` prevents `pyvelm.modules.base` from
  being importable (would double-register every model class). The
  Tags settings view + menu entry moved from `admin` to `partners`
  since partners owns `res.tag`; partners contributes a leaf under
  `admin.settings` via cross-module menu parenting. The framework
  vs example-addon boundary is now explicit.

  ✅ **Additive schema-migration autogen** (`pyvelm.db_autogen` +
  `pyvelm db diff` / `pyvelm db autogen` CLI subcommands):
  - `compute_diff(env, module)` walks every model owned by *module*
    (via `registry._model_module`), pulls `information_schema.columns`
    for each table, and returns a `Diff` of new tables, new columns,
    and orphan columns.
  - `render_migration(diff, from_v, to_v)` emits a `def migrate(env):`
    file matching the project convention. Every `ADD COLUMN` /
    `CREATE TABLE` uses `IF NOT EXISTS`, drops are commented out.
  - **NOT NULL is stripped** from autogenerated `ADD COLUMN`
    statements (Postgres rejects them on populated tables). For
    `required=True` fields the renderer emits a `# TODO: backfill +
    SET NOT NULL` comment with the follow-up DDL spelled out.
  - `pyvelm db diff <module>` prints the delta to stdout; `pyvelm db
    autogen <module>` writes the migration file *and* bumps the
    module's `VERSION` in `__pyvelm__.py`. `--dry-run` previews.
  - Out of scope (hand-written still): renames, type changes,
    data backfills, M2m junction tables.

  ✅ **Documents & attachments** (`ir.attachment` + `pyvelm.storage`,
  base bumped to 0.17.0):
  - `ir.attachment` model: `name`, `datas_fname`, `mimetype`,
    `file_size`, `res_model`, `res_id`, `type` (`binary` | `url`),
    `url`, `storage_key`, `datas` (base64 for db backend). No FK on
    `res_id` — generic across host models, same trick as Odoo.
    `unlink()` deletes backing blobs before dropping rows.
  - `pyvelm.storage` — pluggable backend selector via
    `PYVELM_ATTACHMENT_BACKEND` (default `local`).
    * `LocalStorageBackend` writes to `PYVELM_ATTACHMENT_DIR`
      (default `./data/attachments`) with two-level hex sharding
      (`<aa>/<bb>/<uuid>_<safe-name>`). Path-traversal / absolute
      keys rejected. Empty shard dirs swept on delete.
    * `DbStorageBackend` returns an empty storage_key and expects
      the row's `datas` column to hold the bytes — useful for tests
      and tiny installs where pg_dump captures everything.
  - `/api/attachment/upload` (multipart `file` + optional
    `res_model`/`res_id`) → JSON `{id, name, mimetype, size}`.
    `/api/attachment/{id}/download` streams with
    `Content-Disposition: attachment` and `Cache-Control: private,
    max-age=3600`. `DELETE /api/attachment/{id}` removes row + blob.
    All three require an authenticated session.
  - Form widget: `widget="attachment"` on a *fieldless* arch entry
    (the widget is generic; doesn't need a column on the host
    model). Template at `widgets/attachment.html`, Alpine component
    `pvAttachment` registered in `layouts/main.html`. Drag-and-drop
    drop zone + file picker, in-flight upload chips, existing
    attachments as download links with byte-size badges and delete
    buttons. Read-only mode hides upload + delete affordances.
  - `MailThread.message_post()` and `notify()` grew an
    `attachment_ids` kwarg that re-homes just-uploaded rows onto
    the freshly-created message.
  - Migration `0_16_to_0_17.py` creates the table + a composite
    `(res_model, res_id)` index, plus an idempotent Admin access
    grant so upgraded installs match fresh installs.

  ✅ **Users polish: avatars + reset-password + private fields**
  (base bumped to 0.18.0):
  - `res.users` grew `avatar_url = Char()` — stored as a plain URL
    string so the column is agnostic to whether the bytes are
    external (`https://…`) or local (`/api/attachment/<id>/download`).
  - New form widget `widget="image"` on `Char`/`Text` fields. The
    Alpine component `pvImageWidget` glues a file picker (POSTing to
    the existing `/api/attachment/upload`) to a URL input; both
    write to the same hidden mirror of the bound field. Display mode
    renders a circular preview with an `onerror` fallback to "broken"
    so a dead URL doesn't snap the layout.
  - `Field.private = True` class attribute — `Password` flips it.
    `BaseModel.read()` drops private fields from its default
    field set; `serialize_record()` skips them unconditionally (even
    when the caller asks by name). Programmatic access through the
    descriptor (`user.password` → bcrypt hash) is untouched, so
    `check_password()` still works. Defense in depth: HTTP responses
    can't leak the hash even if a future endpoint forgets to filter.
  - `user.form` view: password field **removed** entirely. The form
    grows a "Reset password" header action (`method="GET"`) that
    navigates to `/web/users/{id}/reset-password`, a stand-alone
    admin reset page. Two text inputs (no current-password check —
    the route relies on `res.users.write` ACL, which only admin
    holds, to gate the operation). On success, the affected user's
    `session_token` is cleared so they're kicked out and must
    re-authenticate. Self-service (`/web/account/password`) still
    requires the current password for non-admins changing their
    own credential.
  - User-menu pill in `layouts/main.html` now shows `<img>` when an
    avatar URL is set, falling back to the colored initial-circle
    when the field is empty *or* the image fails to load.
  - Migration `0_17_to_0_18.py` adds the `avatar_url` column with
    `ADD COLUMN IF NOT EXISTS` so existing rows keep `NULL` (= no
    avatar, renders as initial-circle).

  ✅ **Session-token rotation + draggable form dialog**:
  - Self-service `/web/account/password` POST now mints a fresh
    `session_token` and writes `{password, session_token}` in the
    same atomic update, then sets the new value back on the response
    cookie. All *other* browser sessions for the same user lose
    their lookup match on the next request (we store a single token
    per user) and the current tab stays signed in — symmetric to the
    admin-reset flow which already wiped the token to kick the user
    out of every device.
  - New layout-level component `pvFormDialog` + `window.PvDialog`
    imperative API. A single floating card (the only one — nested
    dialogs replace rather than stack, deferred to a future
    iteration) loaded via `htmx.ajax` into a `[data-pv-form-shell]`
    body. Drag by the title bar (clamped so 60px of the card stays
    in viewport), close by X / ESC / backdrop (backdrop opt-in via
    `closeOnBackdrop`). HTMX requests fired from inside the body get
    a `X-PV-Dialog: 1` header injected via a `htmx:configRequest`
    listener; the server uses that to switch the form-save / form-
    create routes' success path from a body swap to
    `204 + HX-Trigger: pv-dialog-saved` carrying
    `{id, label, model}`. The dialog listens for `pv-dialog-saved`
    on the window, closes itself, and hands the payload to the
    opener's `onResult` callback.
  - Form-body buttons switched from `hx-target="#pyvelm-form-shell"`
    to `hx-target="closest [data-pv-form-shell]"` so the same
    markup works for the page form (shell wrapper in `form.html`)
    and for the dialog (its body is the wrapper). Likewise `Save`
    and `Create` switched their `hx-include` to
    `closest [data-pv-form-shell]` so they grab the inputs of the
    surrounding shell rather than a globally-resolved `#pyvelm-form`
    (which would collide when the page also has a form behind the
    dialog). `web_form_new` learned to honor `HX-Request: true` and
    return the body-only fragment so the dialog can drop the form
    straight into its body without the page chrome.
  - Two consumers wired:
    * M2o combobox's "Create and edit" no longer navigates away —
      it calls `PvDialog.open({url: '<form_view>/new?name=<query>'})`
      with the current search query prefilled as the `name`. On
      `onResult({id, label})` the combobox `pick`s the new value,
      so the parent form keeps composing.
    * O2m table (display mode) rows and the "+ Add" footer link
      both now carry `data-pv-dialog data-pv-dialog-refresh`. The
      delegated click handler in `layouts/main.html` loads the
      target URL into the dialog, and on save fires
      `htmx.ajax('GET', location.pathname, ...)` against the
      outermost `[data-pv-form-shell]` so the o2m table re-renders
      with the freshly-edited / created child row.
  - In-form toolbar buttons that would navigate the host page out
    from under the dialog (new-mode `Cancel` calling `history.back`,
    display-mode `Delete` doing the same on success) carry
    `data-pv-hide-in-dialog`. A CSS rule
    `.pv-fdialog-card [data-pv-hide-in-dialog] { display: none }`
    hides them inside the dialog only; the page-level form still
    shows them. The dialog's own X / ESC / backdrop cover cancel,
    and deletion is still reachable from the comodel's full-page
    form.

  ✅ **Graph + pivot views + `read_group` aggregation**:
  - `BaseModel.read_group(domain, groupby, measures)` — the missing
    read-side aggregation layer. Mirrors `search_count` for ACL +
    record rules + company scope, then issues a single SQL `GROUP BY`
    against the base table and returns one dict per group. Group
    specs accept `"<field>"` or `"<field>:<trunc>"` where trunc ∈
    `day | week | month | quarter | year` (Date / Datetime only) and
    measure specs accept `"<field>[:<agg>]"` where agg ∈
    `sum | avg | min | max | count`. Numeric defaults are `sum`,
    everything else defaults to `count`. The special token
    `"__count"` returns `COUNT(*)` and is *always* added so consumers
    can rely on `row["__count"]` for the group's record count.
    Many2one group-bys get their human labels resolved in a single
    follow-up read per comodel and surfaced as `<spec>__label` on
    each row — no N+1 walk in the renderer.
  - `graph_view(name, model, *, groupby, measure, chart="bar"|"line"|"pie", …)`
    builder + `view_type="graph"` rendering. The renderer feeds the
    `read_group` output into ApexCharts (CDN-loaded, lazy on graph
    pages only) via an Alpine `pvGraph` component that picks up
    theme tokens from the resolved CSS variables so light/dark
    just works. Free-text search re-runs the aggregation server-side
    (no client-side filtering).
  - `pivot_view(name, model, *, row_groupby, col_groupby, measures, …)`
    builder + `view_type="pivot"` rendering. One `read_group` call
    over the cartesian product of row + col group-bys produces a
    flat list; the renderer cross-tabs it into a nested HTML table
    with per-row totals, a grand-total column, and a footer totals
    row. Axes are sorted by value (numeric → numeric ascending,
    everything else string-ascending) with `None` floated last so
    sparse cells don't shuffle the column order.
  - `web_view_page` learned `view_type=="graph"` / `=="pivot"`
    dispatching alongside `list` / `kanban`. Form views still bare-
    URL-only (no top-level page).
  - New view-switcher partial (`_view_switcher.html`) shipped on
    list / kanban / graph / pivot pages — chips for every sibling
    view registered for the same `(module, model)`, ordered list →
    kanban → graph → pivot. The current view is highlighted via
    `brand-soft`. Form views are excluded because their URL needs
    a record id.
  - Demo views on `crm.lead`: `lead.graph` (bar, expected_revenue
    summed by stage) and `lead.pivot` (rows = stage, cols =
    priority, measures = __count + expected_revenue:sum). Menu
    items wired under "CRM" so the demo data shows up immediately.

  ✅ **Interactive graph & pivot toolbars** (v0.2.0):
  - Three new JSON API endpoints in `pyvelm.web`:
    * `GET /api/graph/data?model&groupby&measure&chart&search` →
      `{labels, values, measure_label, chart_type, groupby, measure}`
    * `GET /api/pivot/data?model&row_groupby&col_groupby&measures&search` →
      full cross-tab JSON `{body_rows, header_levels, col_totals, …}`
    * `GET /api/view-fields?model` → `{groupable, measurable}` field
      metadata for toolbar dropdowns (all models)
  - `graph.html` rewritten as Alpine `pvGraphToolbar` component:
    * **Bar / Line / Area / Pie** toggle buttons — switches chart type
      client-side with no server round-trip.
    * **Group by** dropdown — every Char / Integer / M2O / Date /
      Datetime field; Date/Datetime expand to `:day` / `:week` /
      `:month` / `:quarter` / `:year` truncation variants.
    * **Measure** dropdown — Count + every Integer/Float as `sum`
      and `avg` aggregates.
    * Free-text search re-fetches from `/api/graph/data` on submit.
    * `render_graph_page` now injects `groupable_fields` +
      `measurable_fields` into the template for server-side hydration
      (chart visible immediately on first load).
  - `pivot.html` rewritten as Alpine `pvPivotToolbar` component:
    * **Row groupby chips** — add via dropdown, click × to remove.
    * **Column groupby chips** — same.
    * **Measure chips** — multi-select; at least one always kept.
    * **Swap axes button** — flips rows ↔ cols in one click.
    * Free-text search triggers re-fetch via `/api/pivot/data`.
    * `_buildTable()` turns the JSON response into a complete HTML
      table string assigned to `x-html` — no page reload.
    * Server-rendered table shown on first load; client table takes
      over after the first toolbar interaction.
    * `render_pivot_page` injects `groupable_fields`,
      `measurable_fields`, and the current `init_row/col_groupby` +
      `init_measures` for toolbar state initialisation.

---

## v0.4.0 release summary

**Released:** 2026-05-22
**Package version:** `0.4.0` (pyproject.toml)
**Reports module version:** `0.2.0`
**Base module version:** `0.18.0` (unchanged)

### What's in this release

| Area | Highlights |
|---|---|
| **Report Builder** | Optional `reports` module — visual builder, secure JSON→SQL compiler, preview, Excel/CSV/PDF export, daily cron + audit log |
| **Field drill-down** | Odoo-style level-by-level picker (`GET /api/reports/field-level`); deep paths like `company_id.currency_id.symbol` |
| **Columns** | Drag-reorder, per-column format (text/number/integer/currency), alignment, fixed or per-row currency symbol |
| **Order by** | Multi-field sort with priority; sort by fields not shown as columns |
| **UI** | `pvCombo` searchable combobox; list `record_href` / `create_href` for custom URLs |
| **Docs** | [docs/report-builder.md](docs/report-builder.md) in Guides nav |

### Next focus options (post-v0.4.0)

- **Report builder polish** — summary group-by drill-down; non-stored/computed
  detail columns; sample report in `vellum_demo`.
- **Vellum Slice E** — migration DSL (deferred).
- **Deferred infra** — cache rollback, multi-worker rate limiter, nested dialogs.

---

## v0.3.0 release summary

**Released:** 2026-05-22
**Package version:** `0.3.0` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this release

| Area | Highlights |
|---|---|
| **Apps Sync** | **Sync** button reloads models/DATA, additive schema diff, view/menu re-sync; `SYNC_HOOK` manifest hook |
| **Vellum** | Auto `created_at`/`updated_at`; `_guarded` mass-assignment default; timestamp forms read-only |
| **`display_name`** | Computed label on every model (`_rec_name` / `_compute_display_name`) |
| **Console UX** | Breadcrumbs, form record pager (list context), list search bar polish, `pvToast` |
| **Fixes** | Injected `id` field; `loader.reload_models` inside `registry.activate()` |

### Next focus options (post-v0.3.0)

- ~~**Report Builder**~~ — shipped in v0.4.0.
- **Vellum Slice E** — migration DSL (deferred).

---

## v0.2.10 release summary

**Released:** 2026-05-23
**Package version:** `0.2.10` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Examples** | `vellum_demo` views + **Vellum demo** menu in `examples/serve.py` |
| **Console** | `pyvelm make:model --vellum` |
| **Domains** | `{"all": True}` with `<` / `>` / `<=` / `>=` on collection paths |
| **Docs** | [api/vellum.md](docs/api/vellum.md) |

### Next focus options (post-v0.2.10)

  - **Vellum Slice E** — migration DSL (deferred).
  - **M2M command tuples** / transaction boundaries (v0.3 theme).

---

## v0.2.9 release summary

**Released:** 2026-05-23
**Package version:** `0.2.9` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Domains** | `("tag_ids.name", op, val, {"all": True})` universal quantifier |
| **Release** | CI + scripts publish CHANGELOG section to GitHub Releases |

### Next focus options (post-v0.2.9)

  - ~~**Domain** — comparison ops with `all`~~ — shipped in v0.2.10.
  - **Vellum Slice E** — migration DSL (deferred).

---

## v0.2.8 release summary

**Released:** 2026-05-23
**Package version:** `0.2.8` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **M2M cache** | `_m2m_relation_index` — `tag_ids` ↔ `partner_ids` stay in sync |
| **Docs** | [docs/index.md](docs/index.md) home page updated |

### Next focus options (post-v0.2.8)

  - ~~**Universal-quantifier domains**~~ — shipped in v0.2.9 (`{"all": True}`).
  - **Vellum Slice E** — migration DSL (deferred).

---

## v0.2.7 release summary

**Released:** 2026-05-23
**Package version:** `0.2.7` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Domains** | `__or__` sub-leaves with `tag_ids.name`-style paths use `EXISTS` |
| **Cache** | `_m2o_referrers_index` — unlink comodel clears referring M2O + O2M |
| **Tests** | `pyvelm/tests/test_domain.py` |

### Next focus options (post-v0.2.7)

  - ~~**Symmetric M2M cache**~~ — shipped in v0.2.8.
  - **Universal-quantifier domains** — `NOT EXISTS` / `all=True` for collections.
  - **Vellum Slice E** — migration DSL (deferred).

---

## v0.2.6 release summary

**Released:** 2026-05-22
**Package version:** `0.2.6` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Vellum** | `env.query`, scopes, events, fillable/guarded, soft deletes, eager load |
| **Core** | O2M/M2M id tuples on `env.cache`; invalidation on inverse writes |
| **Docs** | [docs/vellum.md](docs/vellum.md); `examples/vellum_smoke.py` |

### Next focus options (post-v0.2.6)

  - **Universal-quantifier domains** — `NOT EXISTS` / `all=True` for collections.
  - ~~**Symmetric M2M cache**~~ — shipped in v0.2.8.
  - **Vellum Slice E** — migration DSL (deferred in design doc).

---

## v0.2.5 release summary

**Released:** 2026-05-22
**Package version:** `0.2.5` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Console** | `make:module` / `model` / `view` / `menu` / `command`; `pyvelm list` |
| **Autogen** | `db autogen --with-views` |
| **Runtime** | `PYVELM_ENV=development\|production`; `docker-compose.dev.yml` |
| **Reload** | Registry re-sync fixes “User model not loaded” |

### Next focus options (post-v0.2.5)

  - **Related paths** — One2many/Many2many hops.
  - ~~**Vellum ORM veneer (Phase 1)**~~ — shipped in v0.2.6.

---

## v0.2.4 release summary

**Released:** 2026-05-22
**Package version:** `0.2.4` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Menus** | `Menus(module)` — short `parent` + `view` names; `view_href` / `menu_ref` |
| **CLI** | `cron` / `db` auto-detect `modules_root` from `pyvelm.toml` |
| **Sidebar** | No literal `None` when group has no icon |

### Next focus options (post-v0.2.4)

  - **Related paths** — One2many/Many2many hops.
  - **Vellum ORM veneer (Phase 1)** — `docs/vellum-design.md`.
  - **Stage 6 Slice 3** — message subtypes + followers.

---

## v0.2.3 release summary

**Released:** 2026-05-22
**Package version:** `0.2.3` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Related** | `related="company_id.currency_id"` — read/write through M2O paths |
| **Readonly** | `readonly=True` on any field; blocks write + form edit |
| **Example** | `partners_pro` adds `company_currency_id` on `res.partner` |

### Next focus options (post-v0.2.3)

  - **Related paths** — One2many/Many2many hops.
  - **Vellum ORM veneer (Phase 1)** — `docs/vellum-design.md`.
  - **Stage 6 Slice 3** — message subtypes + followers.
  - **S3 / minio** attachment backend.

---

## v0.2.2 release summary

**Released:** 2026-05-22
**Package version:** `0.2.2` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Docker scaffold** | `./app/modules` bind-mount on `app` + `cron`; `PYVELM_MODULE_ROOTS` on web service |
| **serve.py** | `_collect_module_roots()` reads `PYVELM_MODULE_ROOTS` |
| **Docs** | README clarifies `app/modules/` + restart / Apps install |

---

## v0.2.1 release summary

**Released:** 2026-05-22
**Package version:** `0.2.1` (pyproject.toml)
**Base module version:** `0.18.0` (unchanged)

### What's in this patch

| Area | Highlights |
|---|---|
| **Inline O2m** | Auto `widget="table"` when comodel has a list view; Add a line / Add row; per-cell 422 playback; drag-reorder via `sequence` |
| **Fix** | Add row clones `template.content` (nested Alpine `<template>` broke `innerHTML`) |
| **M2m** | Chip editor: create / open / edit like M2o |
| **Labels** | `company_id` → Company, `tag_ids` → Tags, etc. (`Field._default_string`) |
| **Dev** | `scripts/test_o2m_addrow.py` Playwright smoke for Add row DOM |

---

## v0.2.0 release summary

**Released:** 2026-05-22
**Package version:** `0.2.0` (pyproject.toml)
**Base module version:** `0.18.0`

### What's in the box

| Area | Highlights |
|---|---|
| **ORM** | Recordsets, all field types, computed fields (`@depends`), `_inherit` model extension, `read_group` aggregation |
| **Module system** | Manifests, dep resolution, transactional install/upgrade, hand-written migrations, `db diff` / `db autogen` CLI |
| **UI** | List, form, kanban, **graph**, **pivot** views; draggable dialog; M2o combobox; M2m chip editor; inline validation; drag-reorder; autosave |
| **Graph/Pivot** | ApexCharts-backed graph view (Bar/Line/Area/Pie toggle); cross-tab pivot view; both fully interactive — groupby, measure, and chart-type selectable without page reload |
| **API** | FastAPI generic CRUD + view endpoints; `/api/graph/data`, `/api/pivot/data`, `/api/view-fields` |
| **Auth** | Session cookies, CSRF tokens, login rate limiting, self-service password change with session-token rotation, admin password reset, `Field.private` |
| **Files** | `ir.attachment`, local + DB storage backends, drag-and-drop upload widget |
| **Workflows** | Server actions, automated actions, cron scheduler, mail threads, outgoing-mail dispatcher |
| **Users** | Avatar upload/URL, profile picture in nav, password field hidden framework-wide |
| **DevX** | TypedDict view shapes, builder helpers, `pyvelm db` CLI, deployment Dockerfile + docker-compose |

### Still deferred

See [Deliberately deferred (will bite us, fix when they do)](#deliberately-deferred-will-bite-us-fix-when-they-do)
for the canonical list. Additional polish items called out in release
notes: m2o search result caching beyond in-flight requests, Monetary
axis labels on graph views, raw SQL edits to M2M junction tables bypassing
ORM invalidation.
