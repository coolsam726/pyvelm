# Getting started

This walks through creating a brand-new **PyVELM** app, from
`pip install pyvelm` to your first custom module showing in the browser.
Three steps:

1. Install the `pyvelm` package and scaffold a project.
2. Boot the app and explore.
3. Add a module.

You don't need to know how the framework works internally to follow
this — the [Architecture](architecture.md) page covers concepts when
you want them.

## 1. Install + scaffold

```bash
# Install pyvelm (pipx keeps it isolated from system python).
pipx install pyvelm

# Scaffold a project. Creates ./my_erp/ with all the wiring.
pyvelm init my_erp
cd my_erp
```

The scaffolder drops a self-contained starter tree — a Dockerfile,
a `docker-compose.yml`, an `app/` directory with the FastAPI boot
script, and `deploy/` templates for systemd + nginx if you want to
deploy bare-metal later. See [CLI → `pyvelm init`](cli.md#pyvelm-init)
for the full tree.

## 2. Boot the app

Three paths — pick whichever fits your machine. Docker is the easiest on a clean
system because it provides Postgres. **SQLite** needs no database server (good for
a quick try or CI).

### Path A — Docker

```bash
cp .env.example .env       # adjust passwords for non-toy use
docker compose up --build
```

The compose file runs Postgres, the web app, and a dedicated cron
worker. When the build finishes, open
`http://localhost:8000/login` and sign in as `admin` / `admin`.

### Path B — local Postgres + venv

```bash
cp .env.example .env
# Edit .env so PYVELM_DSN points at a Postgres database you control.

python3 -m venv venv
source venv/bin/activate
pip install -e .
python -m app.serve --reload
# → http://localhost:8000/login   (admin / admin)
# → http://localhost:8000/docs     (development mode only)
```

`python -m app.serve` defaults to **development** (`PYVELM_ENV=development`):
OpenAPI docs at `/docs`, debug logging, no `Secure` cookies (works on plain HTTP).

For **production** locally: `PYVELM_ENV=production python -m app.serve --host 0.0.0.0`
or use gunicorn as in [Deployment](deployment.md).

### Path C — SQLite (no Postgres)

```bash
cp .env.example .env
# Example:
#   PYVELM_DSN=sqlite:////absolute/path/to/var/app.db
#   PYVELM_DSN_TEST=sqlite:////tmp/pyvelm-test.db

python3 -m venv venv
source venv/bin/activate
pip install -e .
pyvelm db migrate --all    # model-driven schema; skips Postgres-only SQL scripts
python -m app.serve --reload
```

SQLite suits local development and tests. Use **PostgreSQL** for production
multi-worker deployments. See [Database layer (v1.0)](multi-database.md).

### What you'll see

A fresh install is empty — the bundled `base` and `admin` modules
give you the login screen, the sidebar shell, the Apps catalog, and
the settings pages. There's no demo data because this is your
project, not the framework's example tree.

Depending on configuration, visiting `/` as an anonymous user may show
the public landing page (Get started → login). This is controlled by
`PYVELM_LANDING` (default: enabled). If you disable it, `/` redirects
straight to `/login`.

Click around:

- **Apps** — install / upgrade / uninstall modules. The framework's
  `base` and `admin` are already installed.
- **Settings** — manage users, groups, companies.
- **Security** — model access entries, record rules.
- **Workflows** — server actions, automation rules, cron jobs, the
  mail outbox.

## 3. Add a module

Run `pyvelm new` from inside the project — it auto-detects the
modules root via the `pyvelm.toml` marker dropped by `pyvelm init`:

```bash
pyvelm new tasks
```

That creates an **empty shell** under `./app/modules/tasks/` (manifest,
`hooks.py`, empty `models/` and `views/` packages — no models or menus
yet). Add code with generators:

```bash
pyvelm make:model tasks.todo --module=tasks
pyvelm make:view tasks.todo --module=tasks
pyvelm make:menu --view=todo.list --module=tasks
pyvelm make:stubs
```

`make:model` scaffolds `class Todo(models.Model)` (Odoo-style). After
you have records, fluent searches use the same ACL path as `search()`:

```python
open_items = env["tasks.todo"].query().where("active", True).order_by("name").get()
```

Apply schema and register the module:

```bash
pyvelm db autogen tasks --with-views
pyvelm db migrate
# or: docker compose up   # runs migrate, then app + cron
```

**Apps boot** (`app/serve.py`) and **`pyvelm db migrate`** only auto-install
**base** and **admin** on a fresh database; use **Apps → Install**,
**`pyvelm db migrate --module tasks`**, or **`--all`** for everything else.

The Apps page lists `tasks` in the catalog. After migrate it should show
**Installed**; otherwise click **Install**. The shell gains a **tasks** app in the sidebar (and its pages in the
top bar under the default `apps` layout) once menus are synced. See
[Navigation](navigation.md) to switch layouts.

For model changes later, see [Migrations workflow](migrations.md).

`make:stubs` (above) writes `.pyvelm/typing/` and merges
`pyrightconfig.json` so your editor validates model and view string
literals (including `env.query("tasks.todo")`). See
[IDE typing stubs](ide-typing.md).

See the [CLI reference](cli.md#pyvelm-new) for the full command
shape, including the `--in <path>` override when you're working
outside an init'd tree.

## What's next

- **[Declaring models](models.md)** — the field reference, computed
  fields, `_inherit` extensions, `super()` chaining, Eloquent-style
  `.query()` builder.
- **[Building UIs](views.md)** — fluent view builders, list / form /
  kanban arches, widgets, search and filtering.
- **[Modules](modules.md)** — `Manifest.make()`, `views_data`, menus.
- **[Form UX](form-ux.md)** — notebooks, Ctrl+S, save toasts, opening
  related records in a dialog.
- **[Extending views](inheritance.md)** — patching another module's
  arches without forking them.
- **[Security](security.md)** — groups, ACL, record rules,
  multi-company.
- **[Deploying pyvelm](deployment.md)** — Docker layout, gunicorn
  tuning, the cron worker, sending email.
