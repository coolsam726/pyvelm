# Changelog

All notable changes to pyvelm land here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project versions itself with [SemVer](https://semver.org/) once
out of the 0.x line.

## Unreleased

## [0.11.0] — 2026-05-26

Email templates with sandboxed Jinja, sanitized **Html** field, MS Word-shaped
TipTap rich editor, CodeMirror HTML source tab, live preview against any
record of the template's model (in both edit and detail pages), and responsive
form-view grid with `cols` + per-field `colspan`. See
[docs/releases/v0.11.0.md](docs/releases/v0.11.0.md).

### Added

- **`mail.template`** — `pyvelm/mail_template.py`: `name`, `model`, `subject`,
  `body_html` (Html), `active`. `render_preview()`, `send_mail()` queue rendered
  HTML mail through `MailThread`. Admin UI at **Settings → Workflows → Email
  templates**.
- **`Html` field** — `pyvelm/fields.py` + `pyvelm/html_sanitizer.py`. Subclass of
  `Text`; sanitizes on write (allowlisted tags/attrs, drops `<script>`/`<style>`,
  strips `on*=` and `javascript:`, filters `style` for `expression()` / banned
  URLs, drops `<input type="text">`-shaped payloads). Renders through the HTML
  editor widget by default — no `widget="html"` needed.
- **HTML editor widget** — `pyvelm/static/src/mail_editor.js` (esbuild →
  `dist/mail_editor.js`). TipTap **v3** Write tab matching the official
  "Simple Editor" template (StarterKit + TextStyle/Color/Highlight/TextAlign/
  Image/TaskList/TaskItem/Placeholder), CodeMirror 6 HTML Source tab with line
  wrapping + variable autocomplete, sanitized Preview tab.
- **Word-style ribbon toolbar** — five labeled groups (Undo / Styles / Font /
  Paragraph / Insert) with dropdown triggers for Heading, List, Align, and
  Insert; live "current style" label on each trigger; color + highlight
  swatch popovers.
- **Live preview-with-record** — `POST /api/mail/templates/preview` renders the
  current draft (subject + body_html) against an optional `res_id`; record
  picker on the Preview tab; auto-renders on tab switch / on detail page load.
- **Variable picker** — `GET /api/mail/templates/models` /
  `GET /api/mail/templates/variables?model=…` (object / user / company /
  custom-context paths, depth 2). Searchable dropdown in the editor toolbar
  on the Source tab; CodeMirror autocomplete (Ctrl+Space).
- **Form-view grid** — `arch["cols"]` (default 2) and per-section `cols`
  override; `field(name, colspan=N)` or `colspan="full"`. Renderer +
  `form_body.html` use CSS custom properties (`--pv-cols`, `--pv-cols-md`,
  `--cell-span`) and `min()` clamping for clean responsive behavior:
  **1 col on `< md`, `min(cols, 2)` on `md`, full `cols` on `lg+`**.
- **`mail.message`** — new columns `body_is_html`, `template_id` (M2O →
  `mail.template`); SMTP backend now sends HTML alternative when flagged.
- **Tests** — `test_html_sanitizer.py` (14 cases: script/style/iframe stripping,
  `javascript:` URLs, event handlers, CSS injection, mark/task-list/data-attr
  allowlisting, input-type allowlist, Html field integration);
  `test_mail_template.py` (Jinja syntax, legacy `${expr}` rewrite, variable
  discovery, context build; optional Postgres send/dispatch).

### Changed

- **Base module → `0.26.0`** (migration `0_25_to_0_26`): creates `mail_template`
  table, adds `mail_message.body_is_html` / `mail_message.template_id`, grants
  Admin CRUD on `mail.template`.
- **Form section grid** — no longer Tailwind `md:grid-cols-2`; switched to
  `.pv-form-grid` with CSS custom properties so any `cols` value works without
  pre-compiling Tailwind variants.
- **TipTap stack** — upgraded from v2 to **v3.23**; dropped the standalone
  `@tiptap/extension-link` (now bundled in StarterKit v3); added 8 extensions
  for Simple Editor parity.

### Fixed

- **Editor toolbar / TipTap reactivity** — TipTap editor instances now live in a
  module-level `WeakMap` keyed by `$root`, not on the Alpine component, so
  Alpine's reactive Proxy never wraps the editor and ProseMirror's
  transaction-identity check (`tr.before === this.doc`) stops failing with
  "Applying a mismatched transaction".
- **Toolbar focus race** — every toolbar button now uses `@mousedown.prevent`
  so clicking Bold / H1 / list / etc. never blurs the editor.
- **Source-tab edit loss** — `syncAll()` is tab-aware; switching Write ↔ Source
  pushes the latest `this.html` into the destination editor and no longer
  overwrites Source edits with stale Write HTML.

## [0.10.0] — 2026-05-26

Policies, granular UI access gating, public landing page, configurable home URL,
sudo mode, and public attachments. See [docs/releases/v0.10.0.md](docs/releases/v0.10.0.md).

### Added

- **Policies** — `pyvelm/policy.py`, `pyvelm/policies/` (`AdminManagementPolicy`,
  workflow policies); `env.can()` / `env.check_can()`; menu `policy=` and form
  `header_actions` policy gating.
- **Access denied page** — `templates/access_denied.html`; browser HTML 403s;
  minimal shell for `/web/feedback_signals/` and `/web/account/`.
- **Landing page** — `/` for anonymous visitors; `PYVELM_HOME_URL`, `PYVELM_LANDING`.
- **`pyvelm.home`** — `home_url()`, `login_url()`, `render_landing_page()`.
- **Sudo** — `Environment.sudo()` / `BaseModel.sudo()` (keeps real `uid`).
- **Public attachments** — `ir.attachment.public`; public download without login;
  image-widget uploads marked public; migration `0_24_to_0_25`.
- **`pyvelm.security`** — `grant_model_access()`, `user_in_group()`,
  `can_view_apps_catalog()`, `template_access()`.
- **Menu ACL fields** — `ir.ui.menu.access_model`, `access_perm`, `access_policy`;
  migrations `0_21`–`0_24`.
- **Apps catalog gate** — module `CATALOG_ACCESS_MODEL` / `_PERM` / `_POLICY`.
- **Tests** — security, policies, home, policy UI gating, apps catalog, view access.

### Changed

- **Sidebar / dashboard / apps** — management menus use `policy="view_any"`;
  Apps menu and catalog require admin policy; breadcrumbs and brand use
  `PYVELM_HOME_URL`.
- **Workflow ACL** — User read on approvals only; admin lists require write/policy.
- **Base sync** — no longer re-adds **User** group on every reload (backfill is
  migration-only).
- **Everyone grants** — shell read on `res.users` / `res.groups` unchanged;
  admin UI gated by policy instead of `perm="write"` alone.

### Fixed

- **Profile avatar** — saving without a new image no longer stores `False`.
- **Char fields** — `False` and `""` normalize to SQL `NULL`.
- **Workflow install** — `maybe_auto_start_workflow` when schema not ready.
- **Many2one display** — label sudo fallback; list M2O links use `_ids[0]`.
- **Feedback routes** — `PermissionError` renders HTML access denied, not JSON.
- **Transaction rollback** on failed commit when nested tx poisoned.

## [0.9.0] — 2026-05-25

Kanban boards, schema autogen, relational dialog UX, navigation history breadcrumbs,
and framework timestamps. See [docs/releases/v0.9.0.md](docs/releases/v0.9.0.md).

### Added

- **Kanban** — Ungrouped boards use list-style search, filters, group-by, and
  pagination; grouped boards support drag-and-drop across columns and sequence
  reorder (`POST /web/records/…/kanban/move`, arch `sequence=`).
- **Navigation history breadcrumbs** — `ref` + `bc` query params remember List →
  Kanban → Form (Odoo-style); view switcher appends ancestors.
- **Schema autogen** — `pyvelm db diff` / `pyvelm db migrate` detect drift and
  apply safe DDL (including NOT NULL with NULL-row warnings); [docs/migrations.md](docs/migrations.md).
- **Framework timestamps** — `created_at` / `updated_at` on all `BaseModel` records;
  read-only on forms when system-managed.
- **Relational widgets** — Default **dialog** editor for One2many / Many2many when
  the comodel has a form view; `widget="inline"` / `widget="table"` for inline tables.
- **View scaffolding** — `pyvelm make:view` generates list/form from the loaded model
  (`.env` `PYVELM_MODULE_ROOTS`); `--minimal` / `--force` flags.
- **Tests** — `test_kanban_drag`, `test_relational_widgets`, `test_timestamps`,
  `test_db_autogen_constraints`, `test_scaffold_views`, `test_module_roots_env`.

### Changed

- **Partners / vellum_demo examples** — Dialog widgets for O2M/M2M; comment kanban
  with `group_by` + `sequence`; partners `code` sync hook for migrate.
- **List / kanban UI** — Shared search toolbar partial (`_pv_search_toolbar.html`);
  kanban card drag handles; Alpine `pvKanbanBoard` component.

### Fixed

- **Kanban render** — `_arch` no longer passed into card renderer kwargs.
- **`db diff`** — `connection is closed` when counting NULL rows for pending NOT NULL.
- **`make:view`** — Resolves module roots from `.env`; loads full registry for
  dependencies; clearer `--force` error.

## [0.8.0] — 2026-05-25

White-label branding per company, login/profile chrome, and date/datetime picker
fixes for inline tables. See [docs/releases/v0.8.0.md](docs/releases/v0.8.0.md).

### Added

- **White-label branding** — `res.company` fields (`app_name`, `app_tagline`,
  `logo_url`, `logo_url_dark`, `favicon_url`, `copyright_text`, support links,
  `show_powered_by`) with `PYVELM_*` env fallbacks; `pyvelm/branding.py` and layout
  partials; company form **Branding** section in admin.
- **Base migrations** — `0_19_to_0_20.py`, `0_20_to_0_21.py`; base module **0.21.0**.
- **Docs** — [docs/branding.md](docs/branding.md).
- **Tests** — `test_branding.py`.

### Changed

- **Login / password / profile** — branded logo, tagline, and footer; topnav brand on
  account pages without sidebar.
- **Admin menu** — dashboard and menu entries use branding context.

### Fixed

- **Datetime picker** — no double calendar on HTMX re-init; popup floats above inline
  O2M tables and list rows (`pv_datetime_picker.js`, scoped `pvInitDatepickers`).
- **Date picker z-index** — Flowbite dropdown above clipped table cells.
- **Color picker** — `pvColorPicker` fixes Alpine `x-data` quoting on company edit.
- **Profile avatar URL** — image widget uses `type="text"` for attachment paths.
- **Topnav include** — `topnav_page_title` set before `_topnav_brand.html` include.

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
