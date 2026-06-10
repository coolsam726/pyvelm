# PyVELM roadmap

Cross-stack parity with [**velmphp**](https://github.com/coolsam726/velm) (the
semantic PHP port on Laravel + Livewire). PyVELM is the reference implementation
for several subsystems; velmphp has moved ahead in admin shell polish and bundled
reference modules. This document tracks **gaps to close** and **features to keep
leading**.

Work lands via **feature branch → PR** (see [CONTRIBUTING.md](CONTRIBUTING.md)).
Release notes go in [CHANGELOG.md](CHANGELOG.md); design rationale in
[docs/architecture.md](docs/architecture.md).

## Current baseline

| | |
|---|---|
| **Stable** | **v1.1.1** (2026-06-09) |
| **Stack** | FastAPI + HTMX + Tailwind v4 + SQLAlchemy Core |
| **Bundled modules** | `base`, `admin`, `console`, `workflow`, `reports`, `mail_compose`, `file_manager`, `technical`, `geo_data`, `document_layout` |
| **Reference port** | velmphp **v1.0.1** + unreleased **v1.1.0** admin polish |

### Milestone overview

| Milestone | Goal | Status |
|-----------|------|--------|
| **v1.0.0** | Portable DB layer, seeders, Schema migrations, stable PyPI | **Done** |
| **v1.0.1** | Nested menus, versioned docs, MySQL/MariaDB WIP | **Done** |
| **v1.1.0** | Fluent manifests/builders, `models.Model`, query builder, Vellum removal | **Done** |
| **v1.1.1** | `make:module` / generator fixes, ~99% test coverage | **Done** |
| **v1.2.0** | Fluent ORM fields, nested dialogs, geo bootstrap, widget hints | **Done** |
| **v1.2.x** | velmphp shell parity — audit, bulk actions, detail views, reference `partners` | **Planned** |
| **v1.3** | ORM extension ergonomics — mixins, model discovery | **Planned** |
| **v1.4** | Multi-DB routing (preview → production), Oracle/MSSQL smoke | **Planned** (see [docs/multi-database.md](docs/multi-database.md)) |

---

## Parity matrix (pyvelm vs velmphp)

### PyVELM leads (maintain; document for PHP port)

| Feature | Module / area |
|---------|----------------|
| Report Builder (SQL compiler, Excel/CSV/PDF, scheduler) | `reports` |
| Rich email composer | `mail_compose` |
| Document branding + PDF/HTML print | `document_layout` |
| Dev editors for views / menus / attachments | `technical` |
| Policy layer (`env.can()`) | `policy.py` |
| Multi-DB routing preview | `database_routing.py` |
| O2M Excel-style keyboard grid | `pv_o2m_grid.js` |

### velmphp leads (close on pyvelm)

| Feature | velmphp | pyvelm today |
|---------|---------|--------------|
| `system_audit` module | v1.0.1 | — |
| List `bulk_actions` | v1.1.0 | — |
| `DetailView` + `row_actions` | rc3+ | form-only |
| `ActionForm` / view-actions inline forms | v1.0.1 | URL actions only |
| Bundled `partners` reference (graph/pivot/dashboard) | v1.0.1 | `examples/` only |
| `$mixins` (`mail.thread` composable) | rc3 | class inheritance |
| `static::super()` for `_inherit` stacks | rc3 | `self.super()` + `Registry.inherit_chain()` |
| Currency import API | v1.0.1 | models + UI, no import |
| Geo country bootstrap (`PYVELM_GEO_COUNTRY`, TZ/locale detect) | v1.2 | **Done** — bootstrap install + background full seed |
| `mail` as installable module | v1.0.0 | core/base |
| Protected bootstrap modules (uninstall blockers) | v1.0.1 | `base` only |
| Per-module dashboard as default app entry | v1.0.1 | admin home only |
| CLI `module:install` / `sync` / `uninstall` | rc1+ | Apps catalog + migrate |
| Model auto-discovery from `models/` | rc1 | `models/__init__.py` imports |
| Read-only code display (Prism) | v1.1.0 | CodeMirror edit only |
| Theme toggle pill UI | v1.1.0 | icon button |
| Dark mode surface tokens | updated | **synced (v1.1.0)** |

---

## Tier 0 — v1.2 ORM ergonomics (shipped in v1.2.0)

| # | Item | Status |
|---|------|--------|
| 0.1 | **Fluent ORM field chains** | **Done (v1.2.0)** — ``Char().required().tracking()``; ``Many2one("m").ondelete()``; metaclass materializes ``OrmFieldBuilder`` |
| 0.2 | **IDE stubs for builders** | Planned — overload ``Char()`` return type in ``make:stubs`` |

---

## Tier 1 — v1.1 shell parity (velmphp 1.0.0 + 1.1.0)

Target: a third-party author can install pyvelm, open the admin shell, and see
the same list/form/toolbar patterns velmphp documents — without reading PHP
source.

| # | Item | velmphp ref | Notes |
|---|------|-------------|-------|
| 1.1 | **Dark mode tokens** | `velm-tokens.css` `.dark` | **Done (v1.1.0)** — lifted surfaces (`gray-800`/`900`), not OLED black |
| 1.2 | **`system_audit` module** | `packages/modules/modules/system_audit/` | `ir.audit.log`, `ir.login.log`, `ir.user.lifecycle`; optional `PYVELM_AUDIT_DSN`; retention cron; CSV export |
| 1.3 | **List bulk actions** | `bulk_actions` arch | Row checkboxes, select-all, bulk bar, default bulk delete when unlink allowed |
| 1.4 | **`DetailView` + `row_actions`** | `DetailView.php`, `ListRowAction` | Read-only record page separate from form; list links via `detail_view` |
| 1.5 | **`ActionForm` / view-actions** | `ViewActionFormController` | Toolbar quick-add/edit mini-forms at `/web/view-actions/...` |
| 1.6 | **Bundled `partners` module** | `modules/partners/` | Ship in wheel: list, detail, form, kanban, graph, pivot, dashboard; demo page actions |
| 1.7 | **Currency import** | `CurrencyImportService` | On-demand world currencies (RESTcountries or bundled fallback); Settings action |
| 1.8 | **Geo bootstrap polish** | `GeoCountryDetector` | **Done** — `PYVELM_GEO_COUNTRY`; bootstrap install; background full seed |
| 1.9 | **Protected modules** | `AppsCatalog` | Block uninstall of `geo_data`, `file_manager`, etc. with clear blockers in Apps UI |
| 1.10 | **Automation settings UX** | `base/views/automation.php` | Server actions + cron under Settings; code field read-only display |
| 1.11 | **Theme toggle pill** | `velm-theme-toggle` CSS | Match velmphp sun/moon sliding toggle |

**Deferred from v1.1** (velmphp also deferred):

- List inline row edit (Filament-style) — v1.2+
- Separate `/web/account/password` page — pyvelm combines in profile today; split if UX testing demands it

### v1.1 delivery slices

| Slice | Items | Outcome |
|-------|-------|---------|
| **1.1-a** | 1.1 (done), 1.11 | Visual parity — dark mode + theme toggle |
| **1.1-b** | 1.2 | Enterprise audit trail installable from Apps |
| **1.1-c** | 1.3, 1.4, 1.5 | List/detail toolbar parity |
| **1.1-d** | 1.6 | Reference `partners` module authors can copy |
| **1.1-e** | 1.7, 1.8, 1.9, 1.10 | Bootstrap / settings polish |

---

## Tier 2 — v1.2 ORM & module author ergonomics

| # | Item | velmphp ref | Notes |
|---|------|-------------|-------|
| 2.1 | **`$mixins` registration** | `Registry.php` mixins | `mail.thread` via manifest/mixin list, not only subclass |
| 2.2 | **`super()` chaining** | `Model::super()` | **Done** — `self.super()` + `Registry.inherit_chain()` |
| 2.3 | **Model auto-discovery** | `ModuleModelLoader` | Scan `models/*.py` for `BaseModel` subclasses; manifest optional |
| 2.4 | **CLI module commands** | `velm:module:*` | `pyvelm module:install`, `module:sync`, `module:uninstall`, `module:list` |
| 2.5 | **Uninstall `--drop-schema`** | `ModuleInstaller` | Dev-only schema cleanup on uninstall (Apps or CLI) |
| 2.6 | **`mail` optional module** | `mail` module | Split chatter from `base` into installable addon (breaking; major bump) |
| 2.7 | **List inline row edit** | ROADMAP 1.1.0 pending | Double-click / inline edit on list rows |

### Reference addons (examples → optional bundled demos)

Port velmphp demo addons into `examples/` or a `pyvelm-demos` extra:

| Addon | Demonstrates |
|-------|----------------|
| `partners_ext` | `_inherit` on `res.partner` |
| `demo_relations` | M2O/O2M/M2M + `file`/`files` widgets |
| `change_management` | Workflow + mail + rich text vertical slice |

---

## Tier 3 — v1.3 platform (already sketched in CHANGELOG)

| # | Item | Notes |
|---|------|-------|
| 3.1 | **MySQL / MariaDB** production-ready | WIP in 1.0.1; finish dialect + CI smoke |
| 3.2 | **Multi-DB routing** | `PYVELM_DATABASES` preview → supported production path |
| 3.3 | **Oracle / MSSQL** smoke | CI matrix parity with velmphp rc3 |
| 3.4 | **PyPI distribution extras** | `[geo]`, `[pdf]`, optional demo pack |

---

## Tier 4 — Post-stable ecosystem

| Item | Notes |
|------|-------|
| Marketplace / composer-style plugin discovery | velmphp Tier 4 `velmphp/composer-plugin` |
| Shared RFC process | Cross-link `docs/rfcs/` with velmphp where semantics align |
| Cross-port test vectors | Shared domain/compute/mixin fixtures both stacks must pass |

---

## Not planned (pyvelm-specific choices)

| Item | Rationale |
|------|-----------|
| Livewire / Blade shell | PyVELM ships HTMX + Jinja; intentional stack split |
| ApexCharts | Chart.js + read_group API is sufficient; swap only if theming gap remains |
| Filament adapter | Cancelled on PHP side; N/A here |

---

## How to use this doc

1. Pick a **tier** and **slice** for a feature branch (`feature/1.1-b-system-audit`).
2. Implement against velmphp behaviour, not line-by-line port — match **arch keys**,
   **HTTP shapes**, and **user-visible flows**.
3. Add tests mirroring velmphp Pest coverage where practical.
4. Update [CHANGELOG.md](CHANGELOG.md) under **Unreleased**; cut `v1.x.y` when a
   tier slice is complete.

**Last synced with velmphp:** 2026-06-09 (PyVELM **v1.1.0** shipped; velmphp admin polish still unreleased).
