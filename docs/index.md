# pyvelm

An Odoo-style ERP framework in Python. Declarative models, view
inheritance via dict-op patches, HTMX-driven UI, real cron and
mail-dispatch story. Built on PostgreSQL (psycopg 3), FastAPI, and
Jinja2.

Released to [PyPI](https://pypi.org/project/pyvelm/); the
[changelog](https://github.com/example/pyvelm/blob/main/CHANGELOG.md)
tracks user-visible changes.

## Quick start

```bash
git clone https://github.com/example/pyvelm
cd pyvelm
cp .env.example .env       # set PYVELM_DSN
docker compose up --build  # → http://localhost:8000/login  (admin / admin)
```

The bundled demo seeds ~20 partners, 15 CRM leads, tags, sales
users, and a couple of workflow records so the UI is populated on
first boot. See [Getting started](getting-started.md) for a guided
walkthrough — install, then declare your first module.

## Read in this order

If you're new, read these in order:

1. **[Getting started](getting-started.md)** — boot the stack, add
   your first module.
2. **[Declaring models](models.md)** — fields, relationships,
   computed values, model inheritance.
3. **[Building UIs](views.md)** — list, form, and kanban views;
   widgets; the search bar; row reorder.
4. **[Extending views](inheritance.md)** — patch views from another
   module without forking them.
5. **[Modules](modules.md)** — the manifest, data files, the
   loader, writing migrations, the Apps catalog.

Then as you need them:

- **[Security](security.md)** — groups, ACL, record rules,
  multi-company scoping, the login flow.
- **[Deployment](deployment.md)** — Docker, gunicorn, the
  background cron worker, sending email, CSRF / rate-limit /
  password-change.
- **[Architecture](architecture.md)** — design decisions behind
  the API.

The **[API reference](api/index.md)** is auto-generated from
docstrings if you want the per-class details.

## What ships in the wheel

`pyvelm` bundles two modules so a fresh install produces a bootable
app:

- **`base`** — `ir.ui.view`, `res.users`, `res.groups`,
  `ir.model.access`, `ir.rule`, `ir.actions.server`,
  `base.automation`, `ir.cron`, `mail.message`, `res.country`,
  `res.region`, `res.company`, `ir.ui.menu`. Plus the install hook
  that seeds the admin group + uid=1 superuser + ACL defaults +
  the mail-dispatcher cron.
- **`admin`** — list / form views + sidebar menus that put a
  working management UI in front of the base models.

Apps prepend `pyvelm.BUILTIN_MODULE_ROOTS` to their own discovery
roots:

```python
from pyvelm import BUILTIN_MODULE_ROOTS, loader

loader.load_and_install(
    BUILTIN_MODULE_ROOTS + [my_addons_dir],
    env,
)
```

The illustrative addons (`partners`, `partners_pro`, `crm`, `demo`)
live under `examples/` in the repo and are opt-in — they show
patterns rather than being required.

## CLI

```bash
pyvelm-cron --interval 60     # background cron + outgoing-mail dispatcher
```

See [Deployment → Background cron runner](deployment.md#the-cron-worker)
for the production story.
