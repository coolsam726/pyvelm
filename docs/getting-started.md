# Getting started

This walks through creating a brand-new pyvelm app, from
`pip install` to your first custom module showing in the browser.
Three steps:

1. Install pyvelm and scaffold a project.
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

Two paths, pick whichever fits your machine. Docker is the easiest
on a clean system because it provides Postgres too.

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
python -m app.serve
# → http://localhost:8000/login   (admin / admin)
```

### What you'll see

A fresh install is empty — the bundled `base` and `admin` modules
give you the login screen, the sidebar shell, the Apps catalog, and
the settings pages. There's no demo data because this is your
project, not the framework's example tree.

Click around:

- **Apps** — install / upgrade / uninstall modules. The framework's
  `base` and `admin` are already installed.
- **Settings** — manage users, groups, companies.
- **Security** — model access entries, record rules.
- **Workflows** — server actions, automation rules, cron jobs, the
  mail outbox.

## 3. Add a module

`pyvelm new` scaffolds a runnable module skeleton in the project's
`app/modules/` directory. **Coming in the next release** — for
now, you can hand-author the module:

Create `app/modules/tasks/__pyvelm__.py`:

```python
NAME: str = "tasks"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "A tiny task tracker."
CATEGORY: str = "Productivity"
DEPENDS: list[str] = ["base"]
DATA: list[str] = ["views/task.py"]
```

Add an empty `app/modules/tasks/__init__.py`, then declare a model:

```python
# app/modules/tasks/models/__init__.py
from . import task    # noqa: F401
```

```python
# app/modules/tasks/models/task.py
from pyvelm import BaseModel, Boolean, Char, Many2one


class Task(BaseModel):
    _name = "tasks.task"

    title = Char(required=True)
    notes = Char()
    done = Boolean(default=False)
    assignee_id = Many2one("res.users", ondelete="SET NULL")
```

Add a list + form view and a sidebar entry:

```python
# app/modules/tasks/views/task.py
from pyvelm.builders import (
    field, form_view, list_view, menu_group, menu_item, section,
)

VIEWS = [
    list_view(
        "task.list", "tasks.task",
        title="Tasks",
        fields=["title", field("done", widget="toggle"), "assignee_id"],
        form_view="task.form",
    ),
    form_view(
        "task.form", "tasks.task",
        sections=[
            section("main", "Task", [
                "title",
                field("done", widget="toggle"),
                "assignee_id",
                "notes",
            ]),
        ],
    ),
]

MENUS = [
    menu_group("tasks", "Tasks", sequence=60),
    menu_item("tasks.list", "All tasks",
              parent="tasks.tasks",
              href="/web/views/tasks/task.list",
              sequence=10),
]
```

Restart the app (`docker compose restart app` or your service
manager). The Apps page lists your new module under "Productivity".
Click **Install**. Once the toast confirms, the sidebar shows a
**Tasks** group with an **All tasks** entry inside it.

## What's next

- **[Declaring models](models.md)** — the field reference, computed
  fields, model inheritance.
- **[Building UIs](views.md)** — list / form / kanban arches,
  widgets, search and filtering.
- **[Extending views](inheritance.md)** — patching another module's
  arches without forking them.
- **[Security](security.md)** — groups, ACL, record rules,
  multi-company.
- **[Deploying pyvelm](deployment.md)** — Docker layout, gunicorn
  tuning, the cron worker, sending email.
