# pyvelm

An Odoo-style ERP framework in Python, built from first principles. The point
isn't to reinvent Odoo — it's to keep the core ideas visible so the design
trade-offs stay legible while the framework grows.

Status: **v0.9.0** — full-stack ERP framework on PostgreSQL (psycopg 3):
ORM + module loader, list/form/kanban/graph/pivot UI (HTMX), session
auth + ACL + record rules, multi-company, workflows, report builder,
mail/chatter, white-label branding, schema autogen, and `pyvelm init` for
greenfield projects. See [CHANGELOG.md](CHANGELOG.md) and [CONTEXT.md](CONTEXT.md).

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
- [Module loading & migrations](docs/module-loading.md) — manifest format,
  loader lifecycle, the active-registry contextvar, writing migrations.
- [Web layer & views as data](docs/web-layer.md) — `ir.ui.view`, the
  `VIEWS` manifest key, the FastAPI app factory, JSON serialization
  shape, three view types, mutations, inline edit.
- [Access control](docs/acl.md) — the four ACL models, HTTP Basic
  authentication, superuser bypass, record rules, anonymous access
  conventions.
- [Module reference](docs/modules.md) — what lives in each module, the
  public surface, and the invariants worth knowing.
- [Extending fields](docs/extending-fields.md) — implementing a custom field
  type without breaking the cache contract.
- [CONTEXT.md](CONTEXT.md) — current stage state, deferred items, and the
  next concrete task.

## What's deliberately not here yet

Things deferred with eyes open, not by accident: M2M command tuples,
i18n, cache eviction / rollback with transactions, down-migrations,
shared rate limiting across workers, nested dialogs. Module loading,
session auth, additive schema autogen (`pyvelm db autogen`), and
`env.transaction()` for install/web mutations **are** shipped. See
[CONTEXT.md](CONTEXT.md) for the full deferred vs shipped list.
