# pyvelm

Odoo-style ERP framework in Python — recordsets, declarative models,
env-bound cache, view inheritance via dict-op patches, HTMX-driven
UI, and a real cron + mail-dispatch story. Built on PostgreSQL
(psycopg 3), FastAPI, and Jinja2.

## Quick start

```bash
git clone https://github.com/example/pyvelm
cd pyvelm
cp .env.example .env       # set PYVELM_DSN
docker compose up --build  # → http://localhost:8000/login  (admin / admin)
```

The bundled `demo` module seeds ~20 partners, 15 CRM leads, tags,
sales users, and a couple of workflow records so the UI is
populated on first boot.

## What lives where

| Surface | Where to look |
|---|---|
| **Concepts & design** | The [Architecture](architecture.md) overview |
| **Defining models** | [Extending fields](extending-fields.md) + [Module loading](module-loading.md) |
| **Building UIs** | [Web layer](web-layer.md) — views as data, inheritance, widgets, list/form/kanban |
| **Security model** | [ACL & security](acl.md) |
| **Module reference** | [Modules](modules.md) — every package in the framework with its public surface |
| **API reference** | The [API](api/index.md) tab — auto-generated from docstrings |

## What ships in the wheel

`pyvelm` bundles two modules so a fresh `pip install` produces a
bootable app:

- **`base`** — `ir.ui.view`, `res.users`, `res.groups`,
  `ir.model.access`, `ir.rule`, `ir.actions.server`, `base.automation`,
  `ir.cron`, `mail.message`, `res.country`, `res.region`,
  `res.company`, `ir.ui.menu`. Plus the install hook that seeds the
  admin group + uid=1 superuser + ACL defaults + the mail-dispatcher
  cron.
- **`admin`** — list / form views + sidebar menus that put a working
  management UI in front of the base models. No new Python models.

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

See [Web layer → Background cron runner](web-layer.md#background-cron-runner)
for the deployment story (docker-compose ships a dedicated `cron`
service).
