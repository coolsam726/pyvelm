# pyvelm

An Odoo-style ERP framework in Python. Declarative models, view
inheritance via dict-op patches, HTMX-driven UI, real cron and
mail-dispatch story. Built on PostgreSQL (psycopg 3), FastAPI, and
Jinja2.

**Latest release:** [v0.10.0](releases/v0.10.0.md) (2026-05-26) — **Policies**,
**UI access gating**, **landing page**, **sudo**, and **public attachments**.
See [releases](releases/v0.10.0.md) and the
[changelog](https://github.com/coolsam726/pyvelm/blob/main/CHANGELOG.md).

```bash
pip install pyvelm==0.10.0
```

Published on [PyPI](https://pypi.org/project/pyvelm/).

## Quick start

**From PyPI** (scaffold a new app):

```bash
pipx install pyvelm
pyvelm init my_erp
cd my_erp
cp .env.example .env
docker compose up --build   # → http://localhost:8000/login  (admin / admin)
```

**From source** (this repo):

```bash
git clone https://github.com/coolsam726/pyvelm.git
cd pyvelm
cp .env.example .env       # set PYVELM_DSN
pip install -e .
docker compose up --build
```

The bundled demo seeds partners, CRM leads, tags, sales users, and
workflow records so the UI is populated on first boot. See
[Getting started](getting-started.md) for a guided walkthrough.

**Optional checks** (repo examples, same module roots as `examples/serve.py`):

```bash
python examples/basic.py
python examples/vellum_smoke.py
```

## What's new

| Version | Highlights |
|---------|------------|
| [v0.9.0](releases/v0.9.0.md) | **Kanban** drag-drop, schema **db diff/migrate**, dialog O2M/M2M, breadcrumb **history** |
| [v0.8.0](releases/v0.8.0.md) | **White-label branding**, date/datetime picker fixes |
| [v0.7.0](releases/v0.7.0.md) | Form **chatter** (notes, email, attachments), **`tracking=True`** fields, workflow history |
| [v0.6.0](releases/v0.6.0.md) | **[Workflows](workflow.md)** — designer, runtime bar, approvals inbox, stage forms |
| [v0.5.0](releases/v0.5.0.md) | Per-company theme, dashboards, datetime pickers, Feedback Signals example |
| [v0.4.0](releases/v0.4.0.md) | **[Report Builder](report-builder.md)** — drill-down fields, formatting, order by, export |
| [v0.3.0](releases/v0.3.0.md) | **Apps Sync**; Vellum timestamps/`_guarded`; `display_name`; breadcrumbs & pager |
| [v0.2.10](releases/v0.2.10.md) | **Vellum demo** sidebar in example server; `make:model --vellum` |
| [v0.2.9](releases/v0.2.9.md) | `{"all": True}` on `tag_ids.*` domains; GitHub release notes from CHANGELOG |
| [v0.2.8](releases/v0.2.8.md) | Symmetric M2M cache — `partner.tag_ids` write clears stale `tag.partner_ids` |
| [v0.2.7](releases/v0.2.7.md) | `__or__` domains with `tag_ids.name`-style paths; M2O cache cleared when a comodel is unlinked |
| [v0.2.6](releases/v0.2.6.md) | **[Vellum](vellum.md)** — optional Eloquent-style ORM (`env.query`, scopes, soft deletes); O2M/M2M request cache |
| [v0.2.5](releases/v0.2.5.md) | Artisan `pyvelm make:*` generators; `PYVELM_ENV` dev/production; reload registry fix |

Older notes: [v0.2.4](releases/v0.2.4.md) … [v0.2.0](releases/v0.2.0.md).

## Read in this order

If you're new, read these in order:

1. **[Getting started](getting-started.md)** — boot the stack, add
   your first module.
2. **[Declaring models](models.md)** — fields, relationships,
   computed values, model inheritance, dotted search domains.
3. **[Vellum](vellum.md)** — optional Eloquent-style queries and
   ergonomics (`env.query`, scopes, soft deletes).
4. **[Building UIs](views.md)** — list, form, and kanban views;
   widgets; the search bar; row reorder.
5. **[Extending views](inheritance.md)** — patch views from another
   module without forking them.
6. **[Modules](modules.md)** — the manifest, data files, the
   loader, writing migrations, the Apps catalog.
7. **[Report Builder](report-builder.md)** — user-defined reports,
   visual builder, secure SQL compilation, export and scheduling.

Then as you need them:

- **[Security](security.md)** — groups, ACL, record rules,
  multi-company scoping, the login flow.
- **[Deployment](deployment.md)** — Docker, gunicorn, the
  background cron worker, sending email, CSRF / rate-limit /
  password-change.
- **[Console commands](console.md)** — `pyvelm make:module`, `make:model`,
  `db autogen`, and related generators.
- **[Architecture](architecture.md)** — design decisions behind
  the API (cache, domains, deferred items).

The **[API reference](api/index.md)** is auto-generated from
docstrings if you want the per-class details.

## What ships in the wheel

`pyvelm` bundles modules under `pyvelm/modules/` so a fresh install
produces a bootable app:

- **`base`** — `ir.ui.view`, `res.users`, `res.groups`,
  `ir.model.access`, `ir.rule`, `ir.actions.server`,
  `base.automation`, `ir.cron`, `mail.message`, `res.country`,
  `res.region`, `res.company`, `ir.ui.menu`. Plus the install hook
  that seeds the admin group + uid=1 superuser + ACL defaults +
  the mail-dispatcher cron.
- **`admin`** — list / form views + sidebar menus that put a
  working management UI in front of the base models.
- **`reports`** — `ir.report` / `ir.report.run`, visual builder,
  secure compiler, Excel/CSV/PDF export (see
  [Report Builder](report-builder.md)).
- **`console`** — Artisan-style `pyvelm make:*` generators (see
  [Console commands](console.md)).
- **`vellum`** — marker module; import **`pyvelm.vellum`** in your
  models for the optional query-builder veneer (see [Vellum](vellum.md)).

Apps prepend `pyvelm.BUILTIN_MODULE_ROOTS` to their own discovery
roots:

```python
from pyvelm import BUILTIN_MODULE_ROOTS, loader

loader.load_and_install(
    BUILTIN_MODULE_ROOTS + [my_addons_dir],
    env,
)
```

The illustrative addons (`partners`, `partners_pro`, `crm`, `demo`,
`vellum_demo`) live under `examples/` in the repo and are opt-in —
they show patterns rather than being required.

## CLI

```bash
pyvelm init my_erp              # scaffold a project
pyvelm make:module inventory     # empty module shell
pyvelm db autogen my_module      # write migration file from models
pyvelm db migrate               # install/upgrade all modules (deploy)
pyvelm db status                # installed vs manifest versions
pyvelm-cron --interval 60        # background cron + mail dispatcher
```

See [CLI reference](cli.md), [Console commands](console.md), and
[Deployment → Background cron runner](deployment.md#the-cron-worker).
