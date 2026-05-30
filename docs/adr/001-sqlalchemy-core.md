# ADR 001: SQLAlchemy Core as the database boundary

**Status:** Accepted  
**Date:** 2026-05-30  
**Deciders:** pyvelm maintainers  

## Context

Pyvelm today speaks PostgreSQL only: hand-built SQL strings (`%s` binds, `ILIKE`,
`information_schema`, `DROP SCHEMA`), psycopg 3 connections, and
`psycopg_pool.ConnectionPool`. The product goal for **v1.x** is:

1. **Portability (v1.0)** — run on PostgreSQL *or* SQLite with one DSN per process.
2. **Multi-DB routing (v1.1+)** — one process serving many PostgreSQL databases
   (Odoo-style tenancy), built on the same connection layer.

Maintaining parallel SQL for every backend in `model.py`, `domain.py`, and
`db_autogen.py` does not scale.

## Decision

Adopt **[SQLAlchemy Core](https://docs.sqlalchemy.org/en/latest/core/)** (≥2.0) as
the **SQL compilation and introspection boundary**. Add it to **core dependencies**
in `pyproject.toml`.

| Layer | Approach |
|-------|----------|
| ORM | **Do not** use SQLAlchemy ORM — pyvelm keeps `BaseModel`, recordsets, `Registry`. |
| Connections | `sqlalchemy.create_engine` + pool; `Environment.conn` uses a thin adapter. |
| DML/DDL | Compile to Core `insert` / `update` / `delete` / `select` / `Table` DDL. |
| Domain | Emit Core boolean expressions; path/join logic stays in pyvelm. |
| Schema diff | SQLAlchemy `Inspector` instead of Postgres-only catalog queries. |
| Migrations | Bundled `migrations/*.py` remain **Postgres-authored**; SQLite uses greenfield install + `apply_schema_diff`. |

### DSN format

`PYVELM_DSN` accepts SQLAlchemy URLs:

- PostgreSQL (reference): `postgresql+psycopg://user:pass@host:5432/dbname`
- Legacy alias: `postgresql://…` normalised to `postgresql+psycopg://…`
- SQLite (dev/CI): `sqlite:////absolute/path/to/app.db` or `sqlite:///./relative.db`

### Connection adapter

`Environment.conn` keeps a **psycopg-compatible surface** (`.execute(sql, params)`,
`.fetchall()`, `.fetchone()`, `.commit()`) during transition so call sites migrate
incrementally. New code uses `pyvelm.database` helpers.

### Dialect capabilities

`DialectCapabilities` gates backend-specific behaviour (`supports_returning`,
`supports_ilike`, `schema_reset_strategy`, etc.) so SQLite limitations are explicit,
not accidental bugs.

## Consequences

**Positive**

- One compilation path for DML/DDL/domain across backends.
- Inspector-based autogen works on SQLite and future MySQL/Oracle.
- Engine abstraction prepares for v1.1 multi-DB `pool_map` without rewriting ORM.

**Negative**

- New core dependency (~SQLAlchemy 2.x).
- Large touch surface in `model.py`, `domain.py`, `db_autogen.py`, entry points.
- Bundled Postgres migration scripts are not replayed on SQLite.

**Neutral**

- Async SQLAlchemy remains out of scope; HTTP stays async, SQL stays sync.
- Alembic is not adopted; pyvelm migration modules + autogen continue.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Optional `[sql]` extra | Adds friction for the primary v1.0 goal; every app needs portability. |
| Per-backend SQL forks | Unmaintainable as models and domain grow. |
| SQLAlchemy ORM | Duplicates registry/model metaclass; breaks recordset design. |
| Peewee / Django-style ORM | Same duplication problem; less dialect coverage than SQLAlchemy. |

## References

- [docs/multi-database.md](../multi-database.md) — user-facing guide and roadmap
- [CONTEXT.md](../../CONTEXT.md) § Multi-database support
- Plan: v1.0 Postgres+SQLite, v1.1 multi-DB routing, v1.2 MySQL/MariaDB
