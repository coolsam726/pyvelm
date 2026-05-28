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
| `pyrightconfig.json` | Created **only when missing** — points the checker at the stub directory |

`pyvelm init` already ships `pyrightconfig.json` and gitignores `.pyvelm/`.
Older projects pick up the config file on the first `make:stubs` run.

Regenerate stubs whenever you add, rename, or remove models or declarative
views (`VIEWS` / `VIEW_INHERITS` in `DATA` files).

## What gets generated

```
.pyvelm/typing/
├── py.typed                 # PEP 561 marker for this tree
├── __init__.pyi             # re-exports ModelName, QualifiedViewName, …
├── names.pyi                # Literal unions for models and views
├── models_stubs.pyi         # per-model recordset stub classes (navigation)
├── pyvelm/
│   ├── env.pyi              # Environment.__getitem__ overloads
│   └── registry.pyi         # Registry.__getitem__ overloads
└── README.md                # short reminder to re-run make:stubs
```

**Discovery** uses the same module roots as the rest of the CLI:

1. Bundled modules (`base`, `admin`, …) when not using `--app-only`
2. `pyvelm.toml` → `modules_root` (walk up from cwd)
3. `PYVELM_MODULE_ROOTS` from `.env`

Models are loaded from each module's `models/` package; views and menus are
read from paths listed in `DATA` (`.py` files exporting `VIEWS` / `VIEW_INHERITS`).

### Symbol types

| Name | Example | Use |
|------|---------|-----|
| `ModelName` | `"res.partner"`, `"crm.lead"` | Model technical names |
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

An existing `pyrightconfig.json` is **never overwritten**. Delete it manually
if you need to reset paths after moving the stub directory.

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

- **`stubPath`** — merges `pyvelm/env.pyi`, `fields.pyi`, `builders.pyi`
  with the installed package (`env["…"]`, `Many2one("…")`, `view="…"`).
- **`extraPaths`** — lets you `from names import ModelName` in app code.

Where completions apply:

| Location | Example |
|----------|---------|
| `Many2one("…")` | Comodel technical name |
| `m.item(…, view="…")` | Short view name (`ViewSlug`) |
| `env["…"]` | Model technical name (when `env` is typed as `Environment`) |
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
| `env["…"]` not completing | `env` must be typed (`Environment`); ad-hoc untyped locals won't |
| Stubs outdated | Re-run `make:stubs` after model/view changes |

## Limitations

- Stubs reflect **declared** models and `DATA` views, not records created only
  in the database.
- Dynamic domains and runtime-built view refs are not analyzed.
- Very large registries truncate the `Literal` union (see comment in `names.pyi`);
  narrow with `--modules-root` or `--app-only`.
- Record **field** names on recordsets are not completed (only model/view strings).
- The web app and `pyvelm db` commands do **not** auto-generate stubs on
  startup — run `make:stubs` explicitly (or add a pre-commit hook).
