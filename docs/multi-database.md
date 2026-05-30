# Multi-database support

Pyvelm **v1.x** adds portable database backends and (from **v1.1**) optional
multi-database routing on PostgreSQL. This guide is the user-facing companion to
[ADR 001: SQLAlchemy Core](adr/001-sqlalchemy-core.md).

## Two tracks

| Track | What it means | First release |
|-------|---------------|---------------|
| **Portability** | One process, one DSN — run on PostgreSQL *or* SQLite (later MySQL/Oracle) | **v1.0.0** |
| **Multi-DB routing** | One process, many PostgreSQL databases (db selector, per-DB sessions) | **v1.1.0+** |

**v1.0 does not** include Odoo-style database selection UI or a `pool_map` of
tenant databases. Design hooks in the connection layer prepare for v1.1.

## Configuration

Set **`PYVELM_DSN`** to a [SQLAlchemy URL](https://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls):

```bash
# PostgreSQL (production default)
export PYVELM_DSN="postgresql+psycopg://pyvelm:pyvelm@localhost:5432/pyvelm"

# Legacy form (normalised automatically)
export PYVELM_DSN="postgresql://pyvelm:pyvelm@localhost:5432/pyvelm"

# SQLite (dev / CI — single process only)
export PYVELM_DSN="sqlite:////tmp/pyvelm-dev.db"
export PYVELM_DSN="sqlite:///./var/app.db"
```

All CLI commands (`pyvelm migrate`, `pyvelm serve`, cron) read the same variable.

## Backend matrix

| Backend | v1.0 | Role | Constraints |
|---------|------|------|-------------|
| **PostgreSQL** | Supported | Production reference | Bundled module migrations; full feature set |
| **SQLite** | Supported | Dev, CI, embedded demos | Single process; no multi-worker production |
| **MySQL / MariaDB** | Planned v1.2 | Common OSS hosting | — |
| **Oracle** | Planned later | Enterprise | — |

### PostgreSQL

- Reference backend for docs, performance, and bundled `migrations/*.py`.
- Use `postgresql+psycopg://` (psycopg 3 driver).

### SQLite

**Supported for:**

- Local development without Docker Postgres
- Fast CI jobs
- Embedded / offline demos

**Not supported for:**

- Multi-worker production (Gunicorn `workers > 1` on one SQLite file)
- Serverless ephemeral disk (use managed Postgres)
- Replaying historical Postgres-only migration scripts — use **greenfield install**
  + model-driven `apply_schema_diff` instead

Schema reset on SQLite drops all tables (or deletes the file), not
`DROP SCHEMA … CASCADE`.

## Architecture

```
PYVELM_DSN
    └── sqlalchemy.create_engine
            ├── pool (checkout per request / CLI command)
            ├── DialectCapabilities (backend flags)
            └── ConnectionAdapter → Environment.conn
                    ├── model.py (DML / DDL via Core)
                    ├── domain.py (Core boolean expressions)
                    └── db_autogen.py (Inspector)
```

**Unchanged conceptually:** `BaseModel`, recordsets, `env.cache`, domain language,
module loader, views, ACL, `Registry`.

**Not adopted:** SQLAlchemy ORM (see ADR 001).

## Migrations policy

| Source | PostgreSQL | SQLite |
|--------|------------|--------|
| Model-driven install + `apply_schema_diff` | Yes | Yes |
| Bundled `pyvelm/modules/*/migrations/*.py` | Yes (replay on upgrade) | No (Postgres DDL) |
| Hand-written app migrations | Postgres-authored | Greenfield + autogen |

Hand-written migration modules may declare `supported_backends = ("postgresql",)`
(see module migration protocol in [migrations.md](migrations.md)).

## v1.0 exit criteria

- `pyvelm migrate` succeeds on Postgres and SQLite
- `examples/basic.py` (or equivalent smoke) passes on both
- HTTP smoke tests pass in CI for both backends
- Docs updated: [cli.md](cli.md), [deployment.md](deployment.md), [migrations.md](migrations.md)

## Roadmap

| Version | Deliverable |
|---------|-------------|
| **v1.0.0** | SQLAlchemy Core layer; Postgres + SQLite end-to-end |
| **v1.1.0** | Multi-DB routing on Postgres (selector, `pool_map`, session binding) |
| **v1.2.0** | MySQL / MariaDB |
| **Later** | Oracle, optional Alembic for app-authored migrations |

## v1.1: multi-DB routing

When ``PYVELM_DATABASES`` lists tenant Postgres databases:

- **Config** — comma-separated ``key=dsn`` or JSON array (see below)
- **Middleware** — ``DatabaseSelectorMiddleware`` sets the active DB from cookie, host, or ``/web/db/<key>/…`` path
- **`app.state`** — ``pool_map`` and lazy ``registry_cache`` per database
- **Sessions** — bound to the selected database (``pyvelm_db`` cookie)
- **CLI** — ``pyvelm migrate --database tenant_a``
- **UI** — ``/web/database/selector`` (Odoo-style database picker)

Example:

```bash
export PYVELM_DSN="postgresql+psycopg://pyvelm:pyvelm@localhost:5432/main"
export PYVELM_DATABASES='tenant_a=postgresql+psycopg://pyvelm:pyvelm@localhost:5432/tenant_a'
```

Or JSON:

```bash
export PYVELM_DATABASES='[{"key":"tenant_a","dsn":"postgresql+psycopg://…","label":"Tenant A"}]'
```

See [ADR 001](adr/001-sqlalchemy-core.md) and [CONTEXT.md](../CONTEXT.md) for
implementation status.

## Related

- [architecture.md](architecture.md)
- [migrations.md](migrations.md)
- [deployment.md](deployment.md)
- [cli.md](cli.md)
