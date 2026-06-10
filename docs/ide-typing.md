# IDE typing stubs

pyvelm can generate **static typing stubs** so your editor catches typos in
model technical names (`"res.company"`), view names (`"lead.list"`), and
related string literals before you run the app.

The stubs have **no runtime effect** — they exist only for Pyright, Pylance,
and similar checkers.

## Quick start

From a project created with `pyvelm init` (a `pyvelm.toml` at the repo root):

```bash
cd my_erp
pyvelm make:stubs
```

This writes:

| Path | Purpose |
|------|---------|
| `.pyvelm/typing/` | Generated `.pyi` files (`ModelName`, view literals, `env[]` overloads) |
| `pyrightconfig.json` | Created when missing; **merged** on each run (`include`, `stubPath`, …) |

`pyvelm init` already ships `pyrightconfig.json` and gitignores `.pyvelm/`.
Older projects pick up the config file on the first `make:stubs` run.

Regenerate stubs whenever you add, rename, or remove models or declarative
views (`VIEWS` / `VIEW_INHERITS` in `DATA` files).

In **development**, the dev server refreshes stubs automatically on startup
(including each `--reload` cycle) so IDE literals stay current while you edit
models. Disable with ``PYVELM_STUBS_ON_SERVE=0`` or ``pyvelm serve --no-stubs``.
Production mode never runs stub generation.

## What gets generated

```
.pyvelm/typing/
├── py.typed                 # PEP 561 marker for this tree
├── __init__.pyi             # re-exports ModelName, QualifiedViewName, …
├── names.pyi                # Literal unions for models and views (global)
├── models_stubs.pyi         # per-model recordset stub classes (navigation)
├── scopes/                  # per-module stubs (dependency-scoped literals)
│   └── partners/
│       ├── names.pyi        # only partners + DEPENDS models/views
│       └── pyvelm/          # same env/fields/builders layout as above
├── pyvelm/
│   ├── model.pyi            # BaseModel _name / _inherit literals
│   ├── models.pyi           # models.Model (inherits model.pyi)
│   ├── env.pyi              # Environment.__getitem__ overloads
│   ├── registry.pyi         # Registry.__getitem__ overloads
│   ├── security.pyi         # grant_model_access(model=…)
│   ├── fields.pyi           # Many2one/One2many/Many2many comodel + OrmFieldBuilder
│   ├── field_builders.pyi   # OrmFieldBuilder.comodel("…")
│   └── builders/
│       ├── menus.pyi        # menu item view= / model=
│       ├── views.pyi        # ListView.make(…).model(…)
│       └── legacy.pyi       # list_view(…, model, …) factories
└── README.md                # short reminder to re-run make:stubs
```

**Discovery** uses the same module roots as the rest of the CLI:

1. Bundled modules (`base`, `admin`, …) when not using `--app-only`
2. `pyvelm.toml` → `modules_root` (walk up from cwd)
3. `PYVELM_MODULE_ROOTS` from `.env`

Models are loaded from each module's `models/` package; views and menus are
read from paths listed in the manifest (`.data(...)` or legacy `DATA`), from
`.py` files exporting `views_data` (`ViewsData.make()`) or legacy
`VIEWS` / `VIEW_INHERITS` / `MENUS`.

### Symbol types

| Name | Example | Use |
|------|---------|-----|
| `ModelName` | `"res.partner"`, `"crm.lead"` | Model technical names (scoped per module — see below) |
| `QualifiedViewName` | `"crm.lead.list"` | `module.view_name` (globally unique) |
| `ViewName` / `ViewSlug` | `"lead.list"` | Short name within a module (menus, `form_view=`) |

## Command reference

```bash
pyvelm make:stubs [options]
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--output=` | `<project>/.pyvelm/typing` | Stub output directory |
| `--modules-root=` | `pyvelm.toml` + env | Scan only this addons root |
| `--app-only` | off | Skip bundled framework models/views |

Examples:

```bash
# Framework / examples tree (no pyvelm.toml at repo root)
pyvelm make:stubs --modules-root=examples/modules --output=.pyvelm/typing

# App modules only (no base/admin symbols in literals)
pyvelm make:stubs --app-only
```

`make:stubs` **merges** keys into an existing `pyrightconfig.json` (`include`,
`stubPath`, `extraPaths`, `executionEnvironments`, `typeCheckingMode`) without
dropping your custom settings. Delete the file manually if you need a full reset
after moving the stub directory.

### Dependency-scoped model autocomplete

When you edit files inside an addon package (e.g. `examples/modules/partners/`),
Pylance uses a **per-module execution environment** so `ModelName` only lists
models declared in that module **and** every module in its `DEPENDS` chain
(direct and indirect). Sibling addons you do not depend on are excluded — editing
`partners` will not suggest `crm.lead` unless `crm` is reachable through
`DEPENDS`.

The global `.pyvelm/typing/names.pyi` still lists every discovered model (useful
for hooks, scripts, and explicit `from names import ModelName`). Files outside
any discovered addon directory keep that global union.

## Editor setup

### VS Code / Cursor (Pylance)

1. Install pyvelm into the **same interpreter** VS Code selected
   (`Python: Select Interpreter` → your venv with `pip install -e .`).
2. Run `pyvelm make:stubs` (writes stubs and **refreshes** `pyrightconfig.json`).
3. **Developer: Reload Window** if completions do not appear.
4. Set **Python › Analysis: Type Checking Mode** to at least **basic**
   (workspace or user settings). Completions for string literals need
   type checking enabled — `off` will not suggest `ModelName` members.

`make:stubs` sets `include` to every code tree it finds (`app/`,
`examples/modules/`, your `pyvelm.toml` `modules_root`, etc.). If you
only had `["app"]` but edit files under `examples/`, Pylance was not
analyzing those files — that is the most common reason completions
appear to do nothing.

```json
{
  "include": ["app", "examples/modules"],
  "stubPath": ".pyvelm/typing",
  "extraPaths": [".pyvelm/typing"],
  "typeCheckingMode": "basic"
}
```

- **`stubPath`** — merges `pyvelm/env.pyi`, `fields.pyi`, `builders/views.pyi`,
  `builders/legacy.pyi`, `security.pyi`, `builders/menus.pyi` with the installed
  package (`env["…"]`, `ListView.make(…).model("…")`, `Many2one("…")`, …).
- **`extraPaths`** — lets you `from names import ModelName` in app code.

Where completions apply:

| Location | Example |
|----------|---------|
| `ListView.make(…).model("…")` | Model technical name |
| `list_view("n", "…", fields=[…])` | Model technical name (legacy) |
| `grant_model_access(env, "…")` | Model technical name (hooks) |
| `_name = "…"` / `_inherit = "…"` | Model technical name on `models.Model` |
| `Many2one("…")` / `One2many("…", …)` / `Many2many("…")` | Comodel technical name |
| `Many2one().comodel("…")` | Comodel technical name (fluent field builder) |
| `m.item(…, view="…")` | Short view name (`ViewSlug`) |
| `env["…"]` | Model technical name (when `env` is typed as `Environment`) |
| `env.query("…")` | Model technical name → `Query` |
| `env.registry["…"]` | Model technical name → model class |
| `Char().required()` | Fluent ORM field chains return `OrmFieldBuilder` (v1.3+) |
| `recordset.query()` | Returns `Query` (chain methods from `pyvelm.query`) |
| `Query.where(…)` field arg | Plain `str` — field names are not literal-unions yet |
| Record fields | Not stubbed yet (`record.name` stays unstructured) |

### PyCharm

PyCharm does not read `pyrightconfig.json` the same way Pylance does.

1. Run `pyvelm make:stubs`.
2. Right-click **`.pyvelm/typing`** → **Mark Directory as** → **Sources Root**.
3. Use explicit literals where needed:

   ```python
   from names import ModelName, QualifiedViewName

   MODEL: ModelName = "crm.lead"
   ```

`env["model"]` overload merging is best-effort in PyCharm unless you enable a
Pylance-based type checker that honours `pyrightconfig.json`.

## Using stubs in code

**Environment / registry** (after stubs + `pyrightconfig.json`):

```python
company = env["res.company"]   # checked literal; stub recordset type
active = env.query("res.company").where("active", True).get()
cls = env.registry["res.company"]
```

**Views and menus** — annotate or import literals:

```python
from names import QualifiedViewName

VIEW: QualifiedViewName = "crm.lead.kanban"
```

Declarative view authoring already benefits from `pyvelm.types` and
`pyvelm.builders` (shape of `arch`, required keys). Stubs add **name**
resolution on top of that.

## Git: commit or ignore

`pyvelm init` adds `.pyvelm/` to `.gitignore` by default.

| Approach | When |
|----------|------|
| **Ignore** (default) | Each developer runs `make:stubs` locally after pull |
| **Commit** stubs | CI type-check without running the generator; review registry changes in diffs |

`pyrightconfig.json` is usually **committed** (small, stable paths).

## Related tooling

| Tool | Role |
|------|------|
| [`pyvelm.types`](api/types.md) | TypedDicts for manifests, views, menus (author-time shapes) |
| [`pyvelm.builders`](api/builders.md) | Ergonomic view/menu constructors returning those TypedDicts |
| [`pyvelm make:view`](console.md) | Scaffold views from model fields |
| [`pyvelm init`](cli.md) | New project with `pyrightconfig.json` + `.gitignore` |

## Troubleshooting (VS Code)

| Symptom | Fix |
|---------|-----|
| No completions anywhere | Type checking mode `off` → set **basic** or **standard** |
| No completions in `examples/` | Re-run `make:stubs` so `include` lists `examples/modules` |
| `Many2one` / `view=` still plain `str` | Reload window; confirm `stubPath` in `pyrightconfig.json` |
| `env["…"]` / `env.query` not completing | `env` must be typed (`Environment`); ad-hoc untyped locals won't |
| Stubs outdated | Re-run `make:stubs` after model/view changes |

## One2many field specs

`field("line_ids", list_view="move.line.invoice")` and `columns=[...]` are
documented in [One2many on parent forms](one2many-forms.md). Stubs autocomplete
**view names** from generated `names.pyi` the same way as menu `view=` strings;
`columns` entries are plain field names on the comodel (no literal union yet).

## Limitations

- Stubs reflect **declared** models and `DATA` views, not records created only
  in the database.
- Dynamic domains and runtime-built view refs are not analyzed.
- Very large registries truncate the `Literal` union (see comment in `names.pyi`);
  narrow with `--modules-root` or `--app-only`.
- Record **field** names on recordsets and in `Query.where("…")` are not
  completed (only model/view strings).
- The web app and `pyvelm db` commands do **not** auto-generate stubs on
  startup — run `make:stubs` explicitly (or add a pre-commit hook).
