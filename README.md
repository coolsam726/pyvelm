# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **v0.15.x** — full-stack ERP framework on PostgreSQL (psycopg 3):
ORM + module loader, list/form/kanban/graph/pivot UI (HTMX), session
auth + ACL + policies + record rules, multi-company, workflows, report
builder, mail/chatter + **email templates**, **Html** field sanitizer,
rich HTML editor, white-label branding, schema autogen, landing page,
and `pyvelm init` for greenfield projects. See [CHANGELOG.md](CHANGELOG.md)
and [CONTEXT.md](CONTEXT.md).

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env       # then edit PYVELM_DSN
.venv/bin/python examples/basic.py
```

The example smoke test exercises every feature including the HTMX UI.
The compiled CSS bundle lives at `pyvelm/static/dist/pyvelm.css` and
is checked in, so a fresh clone runs without Node. If you want to
hack on styling or component markup:

```bash
npm install            # installs Tailwind v4 + Flowbite into node_modules/
npm run dev            # watch mode: rebuilds dist/pyvelm.css on save
npm run build          # one-shot minified build + Flowbite JS copy
```

The build scans `pyvelm/templates/**/*.html` and `pyvelm/render.py`
for utility classes (Tailwind v4 `@source` directives in
`pyvelm/static/tailwind.css`). Add new utility classes in those files
and the next build picks them up.

The example exercises every feature: CRUD, recordset semantics, all four
relational field types, M2o traversal, computed fields, dependency-graph
invalidation, and the singleton guard.

## Documentation

- [Architecture overview](docs/architecture.md) — the big picture: why
  recordsets, what `env.cache` is for, how the dependency graph works, the
  multi-pass init sequence.
- [Migrations](docs/migrations.md) — schema autogen, module upgrades, writing migrations.
- [Views](docs/views.md) — list / form / kanban, widgets, search and filtering.
- [Security](docs/security.md) — groups, ACL, record rules, multi-company, login flow.
- [Module reference](docs/modules.md) — what lives in each module, the
  public surface, and the invariants worth knowing.
- [IDE typing stubs](docs/ide-typing.md) — `pyvelm make:stubs`, Pyright/Pylance,
  and automatic `pyrightconfig.json` setup.
- [Fields API](docs/api/fields.md) — field types, specs, and widget hooks.
- [CONTEXT.md](CONTEXT.md) — current stage state, deferred items, and the
  next concrete task.

## What's deliberately not here yet

Things deferred with eyes open, not by accident: M2M command tuples,
i18n, cache eviction / rollback with transactions, down-migrations,
shared rate limiting across workers, nested dialogs. Module loading,
session auth, additive schema autogen (`pyvelm db autogen`), and
`env.transaction()` for install/web mutations **are** shipped. See
[CONTEXT.md](CONTEXT.md) for the full deferred vs shipped list.
