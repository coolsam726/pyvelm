# Getting started

This walks through bringing up a pyvelm app from a clean checkout
to a custom module showing in the browser. Three steps:

1. Boot the demo stack with Docker.
2. Wire your own addons root next to the bundled modules.
3. Declare a model, a view, and a sidebar entry.

You don't need to know how the framework works internally to follow
this — the [Architecture](architecture.md) page covers concepts when
you want them.

## 1. Boot the demo

The repo ships a `docker-compose.yml` that runs Postgres, the app,
and a background cron worker. From the project root:

```bash
cp .env.example .env       # adjust passwords for non-toy use
docker compose up --build
```

When the build finishes, open `http://localhost:8000/login` and
sign in as `admin` / `admin`. The bundled demo module seeds ~20
partners and 15 CRM leads so the UI is populated.

Click around:

- **Partners** in the sidebar — a list of contacts with search,
  filter, drag-to-reorder columns, and group-by.
- **CRM → Pipeline** — kanban board with cards per stage.
- **Settings** — manage users, groups, companies, tags.
- **Workflows** — server actions, automation rules, cron jobs, the
  mail outbox.
- **Apps** — install / upgrade / uninstall modules.

## 2. Add your own addons root

`examples/serve.py` shows how an app boots. It uses three discovery
roots in order:

```python
from pyvelm import BUILTIN_MODULE_ROOTS

EXAMPLE_ROOT = HERE / "modules"             # partners, partners_pro, crm
DEMO_ROOT    = HERE / "modules_demo"        # the demo seed module
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [EXAMPLE_ROOT, DEMO_ROOT]

loader.load_and_install(MODULE_ROOTS, env)
app = create_app(reg, pool, module_roots=MODULE_ROOTS)
```

`BUILTIN_MODULE_ROOTS` ships inside the wheel — it's `base` (the
primitives every app needs) plus `admin` (the UI for them). You
prepend your own directories alongside.

For your own work, point at a directory of your choice and add it
to both calls:

```python
MY_ADDONS = HERE / "my_addons"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [MY_ADDONS]
```

## 3. Declare a module

Create `my_addons/tasks/__pyvelm__.py`:

```python
NAME: str = "tasks"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "A tiny task tracker."
CATEGORY: str = "Productivity"
DEPENDS: list[str] = ["base"]
DATA: list[str] = ["views/task.py"]
```

Add an empty `my_addons/tasks/__init__.py`, then declare a model:

```python
# my_addons/tasks/models/__init__.py
from . import task    # noqa: F401
```

```python
# my_addons/tasks/models/task.py
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
# my_addons/tasks/views/task.py
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

Restart the app (`docker compose restart app`). The Apps page lists
your new module under "Productivity". Click **Install**. Once the
toast confirms, the sidebar shows a **Tasks** group with an **All
tasks** entry inside it.

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
