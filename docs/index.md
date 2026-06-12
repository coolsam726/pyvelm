# PyVELM

**Odoo semantics, Laravel ergonomics, and a Tailwind + HTMX shell in Python.**

PyVELM is a declarative framework for building ERP-style business apps with:

- Odoo-like recordsets and module lifecycle
- Fluent model, view, and menu declarations
- FastAPI + Jinja runtime on SQLAlchemy-backed databases (PostgreSQL, SQLite, MySQL/MariaDB, SQL Server, Oracle, and other supported dialects)

## Start here

If you are new, follow this order:

1. [Getting started](getting-started.md) - scaffold, boot, and install your first module.
2. [Learning path](learning-path.md) - a practical day-by-day route for your first week.
3. [Declaring models](models.md) - fields, relations, computed fields, and query patterns.
4. [Building UIs](views.md) - list/form/kanban/detail views with fluent builders.
5. [Modules](modules.md) and [Migrations](migrations.md) - versioning and safe deploy flow.
6. [Security](security.md) and [Deployment](deployment.md) - production basics.

If you already know the concepts and need exact signatures, jump to [API reference](api/index.md).

## Quick start

From PyPI (new app):

```bash
pipx install pyvelm
pyvelm init my_erp
cd my_erp
cp .env.example .env
docker compose up --build
```

From this source repository:

```bash
git clone https://github.com/coolsam726/pyvelm.git
cd pyvelm
cp .env.example .env
pip install -e .
docker compose up --build
```

See [Getting started](getting-started.md) for Docker/local setup, and [Multi-database support](multi-database.md) for backend matrix and DSN examples.

## Documentation map

- Build features: [models](models.md), [views](views.md), [form UX](form-ux.md), [workflows](workflow.md), [report builder](report-builder.md).
- Platform and operations: [security](security.md), [multi-database](multi-database.md), [deployment](deployment.md), [navigation](navigation.md).
- Extensibility: [modules](modules.md), [console commands](console.md), [architecture](architecture.md).
- Release and version docs: [unreleased notes](releases/unreleased.md), [versioned docs](versioning.md).

## CLI essentials

```bash
pyvelm init my_erp
pyvelm new inventory
pyvelm make:model inventory.product --module=inventory
pyvelm make:view inventory.product --module=inventory
pyvelm db autogen inventory
pyvelm db migrate
```

See [CLI reference](cli.md) for full command options.

## Current release

Latest docs target [v1.4.4](releases/v1.4.4.md). Active development notes are in [Unreleased](releases/unreleased.md).

Published package:

```bash
pip install pyvelm==1.4.4
```

