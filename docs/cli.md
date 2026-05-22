# The `pyvelm` command

`pip install pyvelm` puts a single command on your `$PATH`:

```bash
pyvelm <subcommand> [options]
```

Subcommands:

| Command | What it does |
|---|---|
| [`pyvelm cron`](#pyvelm-cron) | Run the background cron + mail-dispatcher worker. |
| [`pyvelm init <name>`](#pyvelm-init) | Scaffold a new pyvelm project. |
| [`pyvelm new <module>`](#pyvelm-new) | Drop a runnable module skeleton into a project. |
| [`pyvelm list`](#artisan-style-commands) | List module commands (`make:module`, your own, …). |
| [`pyvelm make:…`](#artisan-style-commands) | Run an Artisan-style command — see [Console commands](console.md). |

`pyvelm --help` shows built-ins; `pyvelm list` shows module commands;
`pyvelm <name> --help` shows a command's signature.

## Artisan-style commands

Modules can register custom commands (generators, importers, maintenance
tasks) like Laravel Artisan. The bundled **`console`** module provides
`make:module` and `make:command`; your addons add more under
`commands/*.py`.

```bash
pyvelm list
pyvelm make:module inventory
pyvelm make:command inventory:import
pyvelm inventory:import --file=data.csv
```

Full guide: **[Console commands](console.md)**.

## `pyvelm cron`

Long-running loop that ticks `CronJob.run_due` against a connection
pool. Drains the outgoing-mail queue, fires due `ir.cron` jobs,
and exits gracefully on `SIGTERM` / `SIGINT`.

```bash
pyvelm cron [--interval SECONDS] [--roots DIR ...]
```

Configuration:

| Flag / env var | Default | What it does |
|---|---|---|
| `--interval` / `PYVELM_CRON_INTERVAL` | `60` | Seconds between ticks. |
| `--roots` / `PYVELM_MODULE_ROOTS` | — | Colon-separated module-discovery roots. The framework's `BUILTIN_MODULE_ROOTS` are always prepended automatically; only your app's addons need to be listed. |
| `PYVELM_DSN` | — | Required — Postgres DSN. |

Run via Docker (`docker compose up` uses the bundled service),
systemd (see [Deployment](deployment.md)),
or directly in a terminal while developing.

!!! warning "One cron worker per database"
    The runner does a plain SELECT-then-UPDATE without row-level
    locking; running multiple workers against the same DB will
    occasionally double-fire a job at its exact due time. The
    bundled `docker-compose.yml` pins the `cron` service at
    `replicas: 1` for that reason. A future hardening will switch
    to `SELECT … FOR UPDATE SKIP LOCKED` and let workers scale.

## `pyvelm init`

Scaffolds a new pyvelm project. Creates a directory in the current
working directory, populates it with a runnable starter (Dockerfile,
docker-compose.yml, app/serve.py, deploy/ templates for systemd +
nginx, README), and substitutes the project name throughout.

```bash
pyvelm init my_erp
cd my_erp
cp .env.example .env             # set PYVELM_DSN
docker compose up --build        # → http://localhost:8000/login
```

The generated tree:

```
my_erp/
├── .env.example                 # PYVELM_DSN, SMTP knobs, gunicorn vars
├── .gitignore
├── README.md
├── Dockerfile                   # python:3.13-slim + gunicorn
├── docker-compose.yml           # postgres + app + cron
├── gunicorn_conf.py
├── pyproject.toml               # depends on pyvelm; declares the app package
├── pyvelm.toml                  # project marker — `pyvelm new` reads it
├── app/
│   ├── __init__.py
│   ├── serve.py                 # the FastAPI app factory
│   └── modules/                 # your modules will land here
│       └── .gitkeep
└── deploy/
    ├── nginx.conf               # TLS + static-asset alias
    └── systemd/
        ├── <name>.service       # web app service
        └── <name>-cron.service  # background runner
```

The project name must be a Python-identifier shape (starts with a
letter, then letters / digits / underscores; 1–50 chars). The
target directory must not already exist — `pyvelm init` never
overwrites.

After `init`, you have two equivalent ways to bring the app up:

- **Docker** — `docker compose up --build`. The bundled compose
  file runs Postgres + the app + a dedicated cron worker.
- **Bare metal** — `python -m venv venv && source venv/bin/activate
  && pip install -e . && python -m app.serve`. Add the systemd
  units under `deploy/systemd/` and the nginx config under
  `deploy/nginx.conf` when you're ready to put it behind TLS. See
  [Deployment](deployment.md) for the bare-metal walkthrough.

## Legacy `pyvelm-cron` entry point

`pyvelm-cron` (the older single-purpose command) still works as an
alias for `pyvelm cron`. Existing `docker-compose.yml` and systemd
unit files don't need editing when you upgrade — both forms accept
the same `--interval` and `--roots` flags.

New deployments should use `pyvelm cron`; the legacy entry is
documented but not advertised.

## `pyvelm new`

Scaffolds a runnable module skeleton inside an existing project.
Run from anywhere inside a `pyvelm init`'d tree — the command walks
up looking for `pyvelm.toml` and uses its `modules_root` setting.

```bash
cd my_erp                 # inside a project from `pyvelm init`
pyvelm new tasks
# → ./app/modules/tasks/  is created
```

The generated tree (empty shell — no models, views, or menus):

```
tasks/
├── __init__.py
├── __pyvelm__.py          # NAME=tasks, DATA=[] (fill via generators)
├── hooks.py               # optional install(env) stub
├── models/
│   └── __init__.py
├── views/
│   └── __init__.py
├── commands/              # Artisan commands (pyvelm make:command)
└── migrations/
    └── __init__.py
```

Add code with generators (same as `pyvelm make:module`):

```bash
pyvelm make:model tasks.todo --module=tasks
pyvelm make:view tasks.todo --module=tasks
pyvelm make:menu --view=todo.list --module=tasks
```

After scaffolding you typically:

1. Run `pyvelm db autogen tasks` (or `--with-views` to auto-create views).
2. Restart the app (`docker compose restart app`).
3. Open `/web/apps`, find the new module, click **Install**.

### Where the module lands

By default the scaffolder walks up from the current directory
looking for a `pyvelm.toml` marker (dropped by `pyvelm init`) and
uses the `modules_root` it declares. Override with `--in`:

```bash
pyvelm new tasks --in /srv/my_erp/app/modules
```

If no marker is found and you don't pass `--in`, the command exits
with an error explaining both options.

## Legacy `pyvelm-cron` entry point
