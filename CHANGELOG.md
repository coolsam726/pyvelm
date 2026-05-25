# Changelog

All notable changes to pyvelm land here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project versions itself with [SemVer](https://semver.org/) once
out of the 0.x line.

## Unreleased

## [0.7.0] — 2026-05-23

Mail-thread chatter on record forms, Odoo-style field tracking, and workflow
history timeline. See [docs/releases/v0.7.0.md](docs/releases/v0.7.0.md).

### Added

- **Form chatter (Activity panel)** — `MailThread` models get a right-hand
  activity column on display forms: message feed (newest first), filter chips
  (All / Notes / Emails / Changes), **Log note** and **Send email** composer,
  file attachments on messages (`POST /web/chatter/post`, `GET /web/chatter/panel`).
- **Field tracking** — `tracking=True` / `tracking=False` on fields; `write()`
  posts `mail.message` rows with `subtype=mail_tracking` on `MailThread` models.
- **Workflow history timeline** — vertical timeline on the workflow bar from
  workflow chatter and pending approvals.
- **Form activity layout** — `.pv-form-split` grid: main fields left, workflow +
  chatter right on large screens; stacks on small screens.
- **`pyvelm/mail_chatter.py`**, **`pyvelm/mail_tracking.py`** — chatter context,
  posting, and tracking helpers.
- **Tests** — `test_mail_chatter`, `test_mail_tracking`, `test_workflow_history`.

### Changed

- **Workflow UI** — transition confirms and stage forms use **`PvDialog`** instead
  of native `<dialog>`; approve/reject via `approveById()` (fixes Alpine/`tojson`).
- **Partner onboarding** — submit transition lands on **Approved**; workflow
  definition re-synced on partners module sync.
- **Examples** — `tracking=True` on CRM leads, partners, and feedback intake fields.

### Fixed

- **Cron smoke test** — skip/delete jobs when target model is missing from the
  registry; purge leftover `Test cron` rows on base sync.
- **Workflow inbox** — form links use `_form_view_for_model` (no invalid `active`
  on `ir.ui.view`).
- **Graph view** — `model_cls` assigned in `render_graph_page`.
- **Chatter Alpine** — `pvChatter` component and HTMX `initTree` for composer tabs.

## [0.6.0] — 2026-05-23

Visual approval workflows on any model — designer, runtime bar, inbox, and
stage forms. See [docs/releases/v0.6.0.md](docs/releases/v0.6.0.md) and
[docs/workflow.md](docs/workflow.md).

### Added

- **Workflow module (0.2.0)** — state machines with transitions, multi-step
  approvals (any / all / sequential), stage forms, and tasks on any model.
- **Visual designer** — `/web/workflow/build` for states, transitions, approval
  rules, and stage-form fields (record or stage-scoped).
- **Runtime workflow bar** — status bar, start/transition buttons, and inline
  approve/reject on record forms.
- **My approvals inbox** — `/web/workflow/inbox` for pending sign-offs.
- **Auto-start** — optional workflow start on record `create()`.
- **Escalation cron** — overdue approval handler seeded every 15 minutes.
- **`pyvelm/workflow` package** — JSON definition schema, engine, service,
  inbox helpers, and install-time backfill for auto-start.
- **Examples** — partner onboarding workflow (partners + workflow modules);
  feedback intake review workflow (Feedback Signals sync hook).
- **Docs** — [docs/workflow.md](docs/workflow.md).

### Changed

- Workflow confirms and stage forms use the draggable **`PvDialog`** chrome
  (same component as `pvConfirm` / inline form dialogs).

### Fixed

- **`X-PV-Dialog` header** — dialog HTMX requests now tag correctly so
  successful saves close the floating dialog (`$refs.content` fix).
- **Module load order** — partner workflow extension lives in the partners
  example, not core workflow (avoids `_inherit` before partners load).
- **Workflow engine** — safe recordset access via `_first()` instead of
  subscripting empty search results.

## [0.5.0] — 2026-05-23

Per-company branding, declarative dashboards, date/datetime/time pickers, list
column picker, account profile, and the Feedback Signals example module. See
[docs/releases/v0.5.0.md](docs/releases/v0.5.0.md).

### Added

- **Per-company theme** — `res.company.primary_color` (base module **0.19.0**);
  generates a primary palette and injects CSS overrides after `pyvelm.css` on
  main, login, and password layouts.
- **Declarative dashboards** — `dashboard_view`, `chart_widget`, `table_widget`,
  `stat_widget`, `link_widget`; configurable grid `columns`, `colspan='full'`,
  table column subsets; Chart.js rendering and admin home dashboard.
- **Date / datetime / time pickers** — Flowbite inline calendar, combined
  datetime popup (`pv_datetime_picker.js`), and `Time` field type on forms.
- **List column visibility** — `field(..., visible=False)` hides columns by
  default; **Columns** menu toggles fields with per-view `localStorage`.
- **Account profile** — `/web/account/profile` to edit name, email, and password.
- **Menu icons** — Heroicons via `heroicons[jinja]`; menu builders accept string
  icon names (e.g. `icon="square-3-stack-3d"`).
- **`pyvelm.request_env`** — `apply_request_scope()` binds session uid and
  `pyvelm_company` cookie for custom module `get_env` handlers.
- **Color widget** — hex color input on forms (`widget="color"`).
- **`feedback_signals` example** — narrative feedback capture, optional LLM
  analysis (Ollama / OpenRouter), lexicon fallback, signal verify UI, analytics
  dashboard.

### Changed

- **Theme partials** — `_head_init.html` (dark-mode FOUC) and `_head_theme.html`
  (company overrides); `merge_template_context()` for module Jinja environments.

### Fixed

- Custom module routes that defined their own `get_env` without the company
  cookie showed the default indigo theme instead of the active company's color.

## [0.4.0] — 2026-05-22

Visual report builder with drill-down field picker, column formatting, order by,
and Excel/CSV/PDF export. See [docs/report-builder.md](docs/report-builder.md)
and [docs/releases/v0.4.0.md](docs/releases/v0.4.0.md).

### Added

- **Report Builder** — `reports` module: secure JSON compiler (M2o joins,
  O2m/M2m subquery columns), visual builder UI, Odoo-style field drill-down,
  per-column format/align/currency, multi-field order by, preview, Excel/CSV/PDF
  export, daily cron scheduling with attachment output, run audit log.
- **`pvCombo`** — searchable combobox for static option lists (builder, forms).
- **List routing** — `record_href` / `create_href` on list views for custom
  open/create URLs (report builder entry points).

## [0.3.0] — 2026-05-22

Apps Sync, Vellum timestamps and `_guarded`, `display_name`, console UX polish
(breadcrumbs, record pager, list search bar, toasts). Base module remains
`0.18.0`. See [docs/releases/v0.3.0.md](docs/releases/v0.3.0.md).

### Added

- **`display_name`** — every model gets a computed ``display_name`` (override
  ``_rec_name`` to pick the source field, default ``name``; override
  ``_compute_display_name`` for custom formatting).
- **Apps Sync** — installed modules show a **Sync** button when up to date;
  reloads models/DATA, applies additive schema diff (autogen under the hood),
  re-syncs views and menus without uninstall/reinstall.
- **`SYNC_HOOK`** — manifest hook run on Sync/upgrade (same version); e.g.
  `vellum_demo` seeds demo notes/comments via `hooks.sync`.
- **`vellum_demo` demo data** — install/sync hooks create sample rows when tables
  are empty.

### Fixed

- **`id` field** — injected on every model (readonly integer) so dependency paths and
  ``display_name`` fallbacks using ``@depends("id")`` work without declaring ``id``.
- **`loader.reload_models`** — run ``importlib.reload`` inside ``registry.activate()``
  so Apps Sync does not raise “No active pyvelm registry”.
- **Vellum timestamp forms** — `created_at` / `updated_at` are system-set on save;
  edit forms show them read-only instead of writable inputs.

### Changed

- **Vellum mass assignment** — Laravel-style `_guarded` is the default scaffold and
  policy for Vellum models (`_guarded = ["id", "created_at", "updated_at"]` when
  neither `_fillable` nor `_guarded` is declared); `_guarded = ["*"]` blocks all
  keys; forms use the same filter via `parse_form_vals`.
- **Vellum timestamps** — `created_at` / `updated_at` are maintained automatically
  on Vellum models (`_timestamps = False` to disable); new columns need Apps Sync
  or a migration.
- **`loader.install`** — always runs schema setup + `apply_schema_diff` and
  reloads data-file modules on upgrade; returns per-module sync summary.
- **Apps actions** — install/upgrade/sync redirect to `/web/admin` with a full
  page reload (Odoo-style); sync summary shown in a toast after landing.
- **`DISPLAY_NAME`** — optional manifest field for the Apps catalog human title;
  ``NAME`` stays the technical id (shown under the state badge). Defaults from
  ``vellum_demo`` → ``Vellum Demo`` when omitted.
- **Apps catalog UX** — flat grid (max 4 columns), cards with quick-action footer,
  display/technical names, search focused on load; detail page in a card with
  actions pinned top-right above long documentation.
- **`pvToast`** — non-blocking toast stack in the main layout (`window.pvToast`,
  ``HX-Trigger: pv-toast``, ``?pv_flash=`` after Apps actions). Use ``pvAlert``
  when the user must acknowledge (errors, confirms).
- **Confirm/alert dialogs** — ``pvConfirm``, ``pvAlert``, and ``hx-confirm`` now
  use the draggable ``PvDialog`` chrome (same component as inline form dialogs);
  the centered ``<dialog>`` modal was removed.
- **Breadcrumbs** — Home → list view → record on form/detail pages; the list
  crumb links back to the model's list view. List pages show Home → view only
  (menu section labels are no longer inserted between them).
- **Form record pager** — prev/next arrows on display and edit forms follow the
  list view's search, filters, and sort (``?list=module/name&search=…`` on URLs);
  navigation wraps cyclically at the ends of the list.
- **List search bar** — shares a row with the page-size control; visible
  focus ring on the bar; autofocus on list, graph, and pivot views.
- **Lighter borders** — default border token toned down for tables and inputs.

## [0.2.10] — 2026-05-23

Vellum demo in the example server UI, domain `all` on comparisons, `make:model
--vellum`, and API docs for `pyvelm.vellum`. Base module remains `0.18.0`.
See [docs/releases/v0.2.10.md](docs/releases/v0.2.10.md).

### Added

- **`vellum_demo` views/menus** — sidebar **Vellum demo** when running
  `examples/serve.py` (notes, comments, soft notes).
- **`pyvelm make:model --vellum`** — scaffold `Vellum` before `BaseModel` with
  `_fillable`.
- **API** — [docs/api/vellum.md](docs/api/vellum.md) (mkdocstrings).

### Changed

- **Domain `{"all": True}`** — supports `<`, `<=`, `>`, `>=` on collection paths.

## [0.2.9] — 2026-05-23

Universal-quantifier collection domains and CHANGELOG-driven GitHub
release bodies. Base module remains `0.18.0`.
See [docs/releases/v0.2.9.md](docs/releases/v0.2.9.md).

### Added

- **Domain `{"all": True}`** — fourth leaf element on O2m/M2m paths;
  e.g. `("tag_ids.name", "!=", "VIP", {"all": True})` means every tag
  is non-VIP (`NOT EXISTS` over failing members).
- **`scripts/extract_changelog.py`**, **`scripts/tag_release.sh`**, **`scripts/github_release.sh`** — release notes from CHANGELOG.

### Changed

- **GitHub release workflow** — `body_path` from CHANGELOG instead of
  auto-generated commit list (`generate_release_notes: false`).
- **`CONTRIBUTING.md`** — documented tag + GitHub release process.

## [0.2.8] — 2026-05-23

Symmetric Many2many cache invalidation and docs home page refresh.
Base module remains `0.18.0`.
See [docs/releases/v0.2.8.md](docs/releases/v0.2.8.md).

### Added

- **`_m2m_relation_index`** — writing or unlinking one side of a Many2many
  invalidates the symmetric field on the comodel (e.g. `tag_ids` ↔ `partner_ids`).

### Changed

- **`docs/index.md`** — Home page: current release, PyPI quick start, what's new table.

## [0.2.7] — 2026-05-23

Domain hardening: comodel-unlink M2O cache invalidation, `__or__` + collection
paths, architecture doc update. Base module remains `0.18.0`.
See [docs/releases/v0.2.7.md](docs/releases/v0.2.7.md).

### Added

- **`_m2o_referrers_index`** — comodel unlink clears stale Many2one cache on
  referring rows (`ON DELETE SET NULL` / `CASCADE`).
- **`pyvelm/tests/test_domain.py`** — domain SQL compile tests + comodel-unlink
  cache integration test.

### Fixed

- **`__or__` domains** — collection paths (`tag_ids.name`, …) in OR groups
  compile via `EXISTS` instead of raising `NotImplementedError`.

### Changed

- **`docs/architecture.md`** — deferred table reflects O2M/M2M cache and
  comodel-unlink invalidation shipped in v0.2.6+.

## [0.2.6] — 2026-05-22

Optional Vellum ORM veneer, O2M/M2M request cache, user docs and smoke
example. Base module remains `0.18.0`.
See [docs/releases/v0.2.6.md](docs/releases/v0.2.6.md).

### Added

- **Vellum** — optional ORM veneer (`pyvelm.vellum`): `env.query`,
  `@scope`, `@on`, `_fillable` / `_guarded`, `SoftDeletes`, `with_()`,
  `with_count()`, relation helpers. See [docs/vellum.md](docs/vellum.md).
- **O2M/M2M request cache** — `One2many` / `Many2many` read through
  `env.cache` when prefetched or previously loaded.
- **`examples/vellum_smoke.py`** — end-to-end Vellum check against
  `examples/modules/vellum_demo`.

## [0.2.5] — 2026-05-22

Artisan console, code generators, dev/production runtime, reload fix.
Base module remains `0.18.0`.
See [docs/releases/v0.2.5.md](docs/releases/v0.2.5.md).

### Added

- **Artisan-style CLI** (`console` module): `pyvelm make:module`,
  `make:model`, `make:view`, `make:menu`, `make:command`; `pyvelm list`.
- **Minimal module scaffold** — empty shell; use generators instead of
  bundled sample models/views/menus.
- **`pyvelm db autogen --with-views`** — create list+form views for models
  touched by the migration when none exist yet.
- **`PYVELM_ENV`** (`development` | `production`) — API docs, cookie
  `Secure` flags, log level; `docker-compose.dev.yml` for reload in Docker.

### Fixed

- **Model registry on uvicorn `--reload`** — re-register models when Python
  has cached `*.models` packages (fixes “User model not loaded” on login).
- **`console` module** — CLI-only addons skip missing `models/` import.

## [0.2.4] — 2026-05-22

Menus builder, CLI module discovery, sidebar icon fix. Base module
remains `0.18.0`. See [docs/releases/v0.2.4.md](docs/releases/v0.2.4.md).

### Added

- **`Menus(module)`** builder — `parent="business"` and
  `view="partner.list"` resolve to `module.business` and
  `/web/views/<module>/<view>`; cross-module parents via
  `parent=("admin", "settings")`.
- **`view_href`**, **`menu_ref`** helpers for low-level menu declarations.
- **CLI** (`cron`, `db`) auto-detects `modules_root` from `pyvelm.toml`
  (same as `pyvelm new` / scaffold `serve.py`).

### Fixed

- Sidebar no longer renders the literal text **None** when a menu group
  has no icon.

## [0.2.3] — 2026-05-22

Odoo-style **related fields** and model-level **readonly** on all field
types. Base module remains `0.18.0`.
See [docs/releases/v0.2.3.md](docs/releases/v0.2.3.md).

### Added

- **`related="company_id.currency_id"`** on any field type — non-stored
  mirror of a dotted path; reads and writes propagate to the leaf field.
  Many2one-hop paths only for now; cache invalidation via the dependency
  graph.
- **`readonly=True`** on field declarations — blocks `write()` and
  disables form widgets unless the view overrides with
  `field(..., readonly=False)`.
- Example: `res.partner.company_currency_id` in `partners_pro`.

### Changed

- Forms merge model `readonly` into field specs when the view does not
  override it (`spec_readonly`).

## [0.2.2] — 2026-05-22

Patch release for `pyvelm init` Docker workflow. Base module remains
`0.18.0`. See [docs/releases/v0.2.2.md](docs/releases/v0.2.2.md).

### Fixed

- **Scaffold `docker-compose.yml`**: bind-mount `./app/modules` on the
  `app` and `cron` services so new addons from `pyvelm new` appear
  after `docker compose restart app` (no image rebuild required).
- **`app` service** now sets `PYVELM_MODULE_ROOTS` (was only on cron).

### Changed

- **`app/serve.py` scaffold**: `_collect_module_roots()` merges
  `PYVELM_MODULE_ROOTS` with the default `app/modules/` path.
- **README** (project scaffold): documents `app/modules/` layout and
  the Docker restart / Apps install flow.

## [0.2.1] — 2026-05-22

Patch release focused on inline One2many editing and form UX polish.
Base module remains `0.18.0`. See [docs/releases/v0.2.1.md](docs/releases/v0.2.1.md).

### Added

- **Inline O2m tables** auto-enable when the comodel has a list view
  (or when `widget="table"` is set); existing rows render as editable
  `<tr>` cells, with an Odoo-style **Add a line** footer row.
- **O2m validation playback** on failed save (422): per-cell errors
  and posted values are replayed so inline edits are not lost.
- **Many2many chip editor** gains create/open/edit links (parity with
  the Many2one combobox).
- **`scripts/test_o2m_addrow.py`** — Playwright end-to-end check that
  Add row inserts a full table row (not a vertical field stack).

### Fixed

- **O2m Add row** clones `template.content` instead of `innerHTML` —
  nested Alpine `<template>` tags inside M2O cells had been truncating
  the row and stacking fields vertically.
- Inline O2m column layout (hidden inputs in first `<td>`; exclude
  Many2many/One2many from compact inline columns).
- Many2one empty recordset handling in inline cells (no `ensure_one`
  on falsy recordsets).
- **Add row** button moved inside `data-pv-o2m-root` on edit forms.
- **`examples/seed.py`** prepends `BUILTIN_MODULE_ROOTS` so bundled
  `base` is discovered on fresh installs.
- Partner O2m smoke test uses stable record id after rename.

### Changed

- **Default field labels** for relational fields: `company_id` →
  Company, `tag_ids` → Tags, `child_ids` → Children (explicit
  `string=` on the field still wins).
- Inline O2m / form edit CSS polish.

## [0.2.0] — 2026-05-22

Second public release. Base module `0.18.0`. See [docs/releases/v0.2.0.md](docs/releases/v0.2.0.md) for the full announcement.

### Added

- **Graph & pivot views** with `read_group()` aggregation, ApexCharts graph renderer, cross-tab pivot table, view switcher, and live JSON APIs (`/api/graph/data`, `/api/pivot/data`, `/api/view-fields`) for interactive toolbars (chart type, groupby, measures, swap axes).
- **Draggable form dialog** (`pvFormDialog` / `PvDialog.open`) for M2o “Create and edit” and O2m row create/edit without leaving the parent form.
- **`ir.attachment`** + pluggable storage (local / database), upload/download/delete APIs, `widget="attachment"`.
- **User polish:** `avatar_url`, `widget="image"`, `Field.private`, admin password reset page, session-token rotation on self-service password change.
- **`pyvelm db diff`** / **`pyvelm db autogen`** for additive schema migration generation.
- **ECB exchange-rate fetcher.** `base` ships a server action + cron
  (`ECB rate fetcher`) that refreshes `res.currency.rate` from the
  European Central Bank's daily feed. Seeded **inactive**: operators
  opt in from Settings → Scheduled Actions to keep fresh installs
  network-silent. Rebases ECB's EUR-base rates against whichever
  currency carries `rate=1.0` (the implicit reference). Idempotent
  per ECB publication date.
- **Inline O2m drag-reorder.** When an embedded `widget="table"`
  O2m points at a comodel whose list view declares `sequence`, the
  edit table renders a drag handle and persists the new ordering
  through the parent's save (no separate endpoint). Mirrors
  list-view drag-reorder semantics — multiples of 10, gaps preserved
  for future inserts.

- **`pyvelm` CLI** with subcommands (`cron`, `init`, `new`). The
  legacy `pyvelm-cron` entry point keeps working as an alias.
- **`pyvelm init <name>`** scaffolds a self-contained project
  (Dockerfile, docker-compose.yml, gunicorn config, app/serve.py,
  systemd + nginx templates under `deploy/`).
- **`pyvelm new <module>`** drops a runnable module skeleton under
  the project's `modules_root`, auto-detected via `pyvelm.toml`.
- **Bundled modules in the wheel.** `base` (framework primitives)
  and `admin` (their management UI) ship at `pyvelm/modules/`;
  apps prepend `pyvelm.BUILTIN_MODULE_ROOTS` to their discovery
  roots.
- **Background cron + outgoing-mail dispatcher.** `pyvelm cron`
  runs `CronJob.run_due` against a connection pool; the bundled
  base module seeds a "Mail dispatcher" cron that drains
  `mail.message` rows via a pluggable backend (`console` /
  `disabled` / `smtp`).
- **Auth hardening.** CSRF middleware (double-submit cookie),
  `/login` rate limit (5 attempts / 5 min per IP), self-service
  password change at `/web/account/password`.
- **Apps catalog** at `/web/apps` with install / upgrade /
  uninstall actions, search + state filter + category dropdown,
  dry-run preview before destructive actions.
- **Form-UX completeness.** Inline validation errors with
  per-cell red borders; Many2many chip editor; row drag-reorder
  via a `sequence` field.
- **Odoo-style list search.** Single search bar with chip filters,
  Filter By + Group By dropdown auto-generated from column
  metadata, collapsible groups when grouping is active.
- **View inheritance Slice C.** Dict-segment predicates (match
  list entries by any attribute) and a `"**"` wildcard prefix
  (find any descendant where the next segment would succeed).
- **Demo seed module** under `examples/modules_demo/demo` that
  populates the dev UI on first boot (~20 partners, 15 leads,
  tags, sales users, workflow records).
- **MkDocs + Material + mkdocstrings** docs site with auto-API
  reference. Deploys to GitHub Pages on push to `main`.

### Changed

- Documentation rewritten as a user guide: prose pages reorganised
  by user task (`getting-started`, `models`, `views`, `inheritance`,
  `modules`, `security`, `deployment`, `cli`, `architecture`) with
  "Stage N Slice X" markers stripped.
- Strict mode enabled on the docs build so cross-link typos fail
  CI.

## 0.1.0 — initial preview

First public preview. The ORM, view rendering, module loader,
ACL, multi-company scoping, view inheritance (dict-op),
HTMX + Tailwind UI, and a smoke-test suite are all in place.
Versions before this lived in the example app's git history
under `examples/modules/base` etc.
