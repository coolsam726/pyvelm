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
| `pyvelm new <module>` | Drop a runnable module skeleton into a project. **Coming in the next release.** |

`pyvelm --help` shows the current list; `pyvelm <subcommand> --help`
shows the flags for each one.

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

## Coming soon

`pyvelm new <module>` will drop a runnable module skeleton inside
the current project — `__pyvelm__.py` manifest, a sample model, a
sample view, a sample sidebar menu entry, an install hook stub, and
a `migrations/` directory. It accepts `--help` today and exits with
a "coming soon" message; it'll start doing real work in the next
release.
