# The `pyvelm` command

`pip install pyvelm` puts a single command on your `$PATH`:

```bash
pyvelm <subcommand> [options]
```

Subcommands:

| Command | What it does |
|---|---|
| [`pyvelm cron`](#pyvelm-cron) | Run the background cron + mail-dispatcher worker. |
| `pyvelm init <name>` | Scaffold a new pyvelm project. **Coming in the next release.** |
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

## Legacy `pyvelm-cron` entry point

`pyvelm-cron` (the older single-purpose command) still works as an
alias for `pyvelm cron`. Existing `docker-compose.yml` and systemd
unit files don't need editing when you upgrade — both forms accept
the same `--interval` and `--roots` flags.

New deployments should use `pyvelm cron`; the legacy entry is
documented but not advertised.

## Coming soon

The unified CLI is the entry surface for the next two pieces of
project tooling:

- **`pyvelm init <name>`** will scaffold a self-contained starter
  project — a directory containing `pyproject.toml` (depending on
  `pyvelm`), a `Dockerfile`, a `docker-compose.yml`, a bare-metal
  `deploy/` directory (systemd unit templates + nginx config), an
  `app/serve.py` boot script, and an `app/modules/` directory where
  your modules live.
- **`pyvelm new <module>`** will drop a runnable module skeleton
  inside the current project — `__pyvelm__.py` manifest, a sample
  model, a sample view, a sample sidebar menu entry, an install
  hook stub, and a `migrations/` directory.

Both subcommands accept `--help` today and exit with a "coming soon"
message — they'll start doing real work in upcoming releases.
