# Changelog

All notable changes to pyvelm land here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project versions itself with [SemVer](https://semver.org/) once
out of the 0.x line.

## Unreleased

### Added

- *(nothing yet)*

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
