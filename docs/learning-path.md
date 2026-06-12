# Learning path

This page is a practical route for a new developer learning PyVELM.

If you are starting from zero, follow the sections in order. If you already know
Odoo-style ORM patterns, jump to day 2.

## Day 1: Run the app and inspect the shell

1. Complete [Getting started](getting-started.md).
2. Confirm you can log in and open **Apps**, **Settings**, and **Security**.
3. Create one module with `pyvelm new <name>` and inspect the generated files.

Goal: understand the project layout and install flow.

## Day 2: Define your first model

1. Read [Declaring models](models.md).
2. Generate a model and view skeleton:

```bash
pyvelm make:model tasks.todo --module=tasks
pyvelm make:view tasks.todo --module=tasks
pyvelm make:menu --view=todo.list --module=tasks
```

3. Run migration commands and install the module.

Goal: comfortably create fields, relations, and basic CRUD screens.

## Day 3: Build better UIs

1. Read [Building UIs](views.md) and [Form UX](form-ux.md).
2. Add one list filter/domain and one form section/notebook.
3. Add an embedded relation using [One2many on forms](one2many-forms.md).

Goal: move from generated views to intentional UX.

## Day 4: Understand module lifecycle

1. Read [Modules](modules.md).
2. Read [Migrations](migrations.md).
3. Practice `pyvelm db diff`, `pyvelm db autogen`, and `pyvelm db migrate`.

Goal: ship changes safely with versioned modules.

## Day 5: Secure and ship

1. Read [Security](security.md).
2. Read [Deployment](deployment.md).
3. Configure a non-default admin password and verify cron setup.

Goal: understand default security posture and deployment responsibilities.

## Day 6+: Pick a specialization

- Product/app track: [Workflows](workflow.md), [Report Builder](report-builder.md), [Email composer](mail-compose.md), [File library](file-manager.md).
- Platform track: [Database layer (v1.0)](multi-database.md), [Shell navigation](navigation.md), [White-label branding](branding.md).
- Framework contributor track: [Console commands](console.md), [Architecture](architecture.md), [API reference](api/index.md).

## Quick command loop

Use this loop as you iterate:

```bash
pyvelm db diff <module>
pyvelm db autogen <module>
pyvelm db migrate
```

When your editor needs stronger autocomplete and literal checks:

```bash
pyvelm make:stubs
```

