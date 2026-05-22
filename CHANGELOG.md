# Changelog

All notable changes to pyvelm land here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project versions itself with [SemVer](https://semver.org/) once
out of the 0.x line.

## Unreleased

### Added

- *(nothing yet)*

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
